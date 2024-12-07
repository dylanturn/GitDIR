from flask import Flask, request, Response, send_file
import os
import zlib
import argparse
import hashlib
import tempfile
import subprocess
from werkzeug.wsgi import wrap_file
from werkzeug.utils import secure_filename
import logging
from logging.config import dictConfig
import struct
import time

# Configure logging
dictConfig({
    'version': 1,
    'formatters': {
        'default': {
            'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
        }
    },
    'handlers': {
        'wsgi': {
            'class': 'logging.StreamHandler',
            'stream': 'ext://flask.logging.wsgi_errors_stream',
            'formatter': 'default'
        }
    },
    'root': {
        'level': 'DEBUG',
        'handlers': ['wsgi']
    }
})

app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)

# Enable Werkzeug debug logging
logging.getLogger('werkzeug').setLevel(logging.DEBUG)

# Store the target directory as a global variable
TARGET_DIR = os.getcwd()

# Global cache for git objects
GIT_OBJECTS = {}
CURRENT_COMMIT_SHA = None

def pack_refs_response(directory):
    """Generate a git pack-refs response for the directory"""
    global CURRENT_COMMIT_SHA
    
    # If we don't have a commit SHA yet, create all objects
    if not CURRENT_COMMIT_SHA:
        create_all_objects(directory)
    
    # Add capabilities after null byte
    capabilities = "multi_ack_detailed thin-pack side-band side-band-64k ofs-delta"
    
    # Format refs response with both HEAD and main branch
    # Note: HEAD must come first in the response
    refs = [
        f"{CURRENT_COMMIT_SHA} HEAD\0{capabilities}",  # First ref includes capabilities
        f"{CURRENT_COMMIT_SHA} refs/heads/main",       # Subsequent refs don't include capabilities
    ]
    
    return "\n".join(refs) + "\n"

def create_all_objects(directory):
    """Create all git objects for the directory and cache them"""
    global GIT_OBJECTS, CURRENT_COMMIT_SHA
    
    tree_entries = []
    
    # First pass: create blob objects for all files
    for root, _, files in os.walk(directory):
        for file in files:
            # Skip .git directory and our special files
            if '.git' in root.split(os.sep) or file.startswith('.'):
                continue
            
            filepath = os.path.join(root, file)
            relpath = os.path.relpath(filepath, directory)
            
            # Read file content
            with open(filepath, 'rb') as f:
                content = f.read()
            
            # Create blob object
            sha1, data = create_blob_object(content)
            GIT_OBJECTS[sha1] = data
            
            # Store entry for tree object
            # Mode 100644 for regular files
            tree_entries.append(('100644', relpath, sha1))
    
    # Create tree object
    tree_sha1, tree_data = create_tree_object(tree_entries)
    GIT_OBJECTS[tree_sha1] = tree_data
    
    # Create commit object
    commit_sha1, commit_data = create_commit_object(tree_sha1)
    GIT_OBJECTS[commit_sha1] = commit_data
    CURRENT_COMMIT_SHA = commit_sha1

def create_blob_object(data):
    """Create a git blob object from file data"""
    # Format: "blob" SP <content length> NUL <content>
    header = f"blob {len(data)}\x00".encode()
    store = header + data
    sha1 = hashlib.sha1(store).hexdigest()
    return sha1, store

def create_tree_object(entries):
    """Create a git tree object from a list of entries
    Each entry is (mode, name, sha1)"""
    # Format: <mode> SP <name> NUL <SHA-1 in binary>
    tree_content = bytearray()
    for mode, name, sha1 in sorted(entries):  # Sort entries for consistent hashing
        # Convert SHA-1 from hex to binary
        sha1_bin = bytes.fromhex(sha1)
        entry = f"{mode} {name}\x00".encode()
        tree_content.extend(entry + sha1_bin)
    
    # Add header
    header = f"tree {len(tree_content)}\x00".encode()
    store = header + tree_content
    sha1 = hashlib.sha1(store).hexdigest()
    return sha1, store

def create_commit_object(tree_sha1, message="Initial commit", parent=None):
    """Create a git commit object"""
    timestamp = int(time.time())
    timezone = "-0600"  # Hardcoded for simplicity
    author = "GitDIR <gitdir@localhost>"
    
    commit_content = [f"tree {tree_sha1}"]
    if parent:
        commit_content.append(f"parent {parent}")
    commit_content.extend([
        f"author {author} {timestamp} {timezone}",
        f"committer {author} {timestamp} {timezone}",
        "",
        message
    ])
    
    content = "\n".join(commit_content).encode()
    header = f"commit {len(content)}\x00".encode()
    store = header + content
    sha1 = hashlib.sha1(store).hexdigest()
    return sha1, store

def write_size_encoding(size):
    """Write variable length size encoding"""
    ret = bytearray()
    c = size & 0x7f
    size >>= 7
    while size:
        ret.append(c | 0x80)
        c = size & 0x7f
        size >>= 7
    ret.append(c)
    return ret

def create_pack_header(num_objects):
    """Create a packfile header"""
    # Format: "PACK" <version=2> <num_objects>
    return b'PACK' + struct.pack('>II', 2, num_objects)

def create_pack_data(want_ref):
    """Create a git packfile containing requested objects"""
    global GIT_OBJECTS
    
    if want_ref not in GIT_OBJECTS:
        app.logger.error(f"Requested object {want_ref} not found")
        return None
    
    # Get all objects reachable from the wanted commit
    objects_to_pack = {}
    
    # Start with the commit
    objects_to_pack[want_ref] = GIT_OBJECTS[want_ref]
    
    # Add tree and blobs
    commit_data = GIT_OBJECTS[want_ref]
    tree_sha = None
    
    # Parse commit object to find tree
    _, content = commit_data.split(b'\x00', 1)
    for line in content.split(b'\n'):
        if line.startswith(b'tree '):
            tree_sha = line.split()[1].decode()
            break
    
    if tree_sha:
        objects_to_pack[tree_sha] = GIT_OBJECTS[tree_sha]
        tree_data = GIT_OBJECTS[tree_sha]
        
        # Parse tree entries to find blobs
        _, content = tree_data.split(b'\x00', 1)
        pos = 0
        while pos < len(content):
            # Find the null byte that separates mode+name from SHA
            null_pos = content.find(b'\x00', pos)
            if null_pos == -1:
                break
                
            # Extract SHA (20 bytes after null)
            sha_bin = content[null_pos + 1:null_pos + 21]
            sha = sha_bin.hex()
            
            if sha in GIT_OBJECTS:
                objects_to_pack[sha] = GIT_OBJECTS[sha]
            
            pos = null_pos + 21
    
    # Create packfile
    pack_data = bytearray()
    
    # Pack header: PACK + version(=2) + number of objects
    pack_data.extend(b'PACK')
    pack_data.extend(struct.pack('>II', 2, len(objects_to_pack)))
    
    # Add each object
    for sha1, data in objects_to_pack.items():
        # Determine object type
        if data.startswith(b'commit '):
            obj_type = 1
        elif data.startswith(b'tree '):
            obj_type = 2
        else:  # blob
            obj_type = 3
        
        # Get the actual content (after header)
        _, content = data.split(b'\x00', 1)
        
        # Compress the content
        compressed = zlib.compress(content)
        
        # Write type and size
        size = len(content)
        byte = (obj_type << 4) | (size & 0x0f)
        size >>= 4
        
        if size:
            # More bytes needed
            byte |= 0x80
        pack_data.append(byte)
        
        # Write remaining size bytes if any
        while size:
            byte = size & 0x7f
            size >>= 7
            if size:
                byte |= 0x80
            pack_data.append(byte)
        
        # Write compressed data
        pack_data.extend(compressed)
    
    # Add pack checksum
    pack_data.extend(hashlib.sha1(pack_data).digest())
    
    app.logger.debug(f"Created packfile with {len(objects_to_pack)} objects, size: {len(pack_data)} bytes")
    return pack_data

def parse_pkt_line(data):
    """Parse a Git protocol packet line."""
    if not data:
        return None
    try:
        # Each line starts with 4 hex digits indicating length
        length = int(data[:4], 16)
        if length == 0:
            return None  # Flush packet
        # Length includes the 4 bytes of the length itself
        return data[4:length]
    except ValueError:
        return None

@app.route('/info/refs')
def info_refs():
    """Handle git clone initial negotiation"""
    service = request.args.get('service')
    if service not in ['git-upload-pack']:
        return "Service not available", 403
    
    # Format each packet with proper length prefix
    service_line = f"# service={service}\n"
    service_packet = f"{len(service_line) + 4:04x}{service_line}"
    
    # Get refs and format with length prefix
    refs = pack_refs_response(TARGET_DIR)
    refs_packet = f"{len(refs) + 4:04x}{refs}"
    
    # Add capabilities advertisement
    response = (
        service_packet +
        "0000" +  # Flush packet
        refs_packet +
        "0000"    # Flush packet
    )
    
    headers = {
        'Content-Type': f'application/x-{service}-advertisement',
        'Cache-Control': 'no-cache',
        'Expires': 'Fri, 01 Jan 1980 00:00:00 GMT',
        'Pragma': 'no-cache'
    }
    
    return Response(response, headers=headers)

@app.route('/git-upload-pack', methods=['POST'])
def upload_pack():
    """Handle git fetch/clone data transfer"""
    try:
        if request.headers.get('Content-Type') != 'application/x-git-upload-pack-request':
            return "Invalid Content-Type", 400

        app.logger.info("\n=== Git Upload Pack Request ===")
        app.logger.info(f"Content-Type: {request.headers.get('Content-Type')}")
        app.logger.info(f"Headers: {dict(request.headers)}")
        
        # Parse client's want/have lines
        client_data = request.get_data().decode('utf-8')
        app.logger.info(f"Raw client data: {client_data}")
        
        # Extract the wanted ref by parsing the packet lines
        want_ref = None
        have_refs = []
        start = 0
        while start < len(client_data):
            pkt_line = parse_pkt_line(client_data[start:])
            if not pkt_line:  # Flush packet
                start += 4
                continue
                
            app.logger.debug(f"Parsed packet line: {pkt_line}")
            if pkt_line.startswith('want '):
                want_ref = pkt_line.split(' ')[1].strip()
            elif pkt_line.startswith('have '):
                have_refs.append(pkt_line.split(' ')[1].strip())
                
            # Move to next packet
            start += int(client_data[start:start+4], 16)
        
        if not want_ref:
            app.logger.error("No wanted refs found in client data")
            return "No wanted refs", 400
            
        app.logger.info(f"Client wants ref: {want_ref}")
        app.logger.info(f"Client has refs: {have_refs}")
        
        # Create packfile for requested objects
        pack_data = create_pack_data(want_ref)
        if pack_data is None:
            return f"Object {want_ref} not found", 404
            
        app.logger.info(f"Created packfile of size: {len(pack_data)}")
        
        # Format the response with proper Git protocol
        response = bytearray()
        
        # Send NAK to indicate no common objects
        response.extend(b"0008NAK\n")
        app.logger.debug("Added NAK packet")
        
        # Send packfile data in side-band-64k format
        # Each packet: length prefix + side-band byte + data
        # Length includes the side-band byte but not the length prefix
        
        # Split pack data into chunks (64KB max as per side-band-64k)
        CHUNK_SIZE = 65520  # 64KB - overhead
        chunks = [pack_data[i:i + CHUNK_SIZE] for i in range(0, len(pack_data), CHUNK_SIZE)]
        app.logger.debug(f"Split pack data into {len(chunks)} chunks")
        
        for i, chunk in enumerate(chunks, 1):
            # Length includes the side-band byte (0x01)
            length = len(chunk) + 1
            length_prefix = f"{length + 4:04x}".encode()
            
            # Format: XXXX<side-band><data>
            response.extend(length_prefix)
            response.append(0x01)  # side-band byte for pack data
            response.extend(chunk)
            app.logger.debug(f"Added chunk {i}/{len(chunks)}: size={len(chunk)}, length prefix={length_prefix}")
        
        # Progress messages on side-band channel 2
        progress_msg = f"Sending {len(chunks)} chunks...\n".encode()
        progress_len = len(progress_msg) + 1
        response.extend(f"{progress_len + 4:04x}".encode() + b"\x02" + progress_msg)
        
        # End with flush packet
        response.extend(b"0000")
        app.logger.debug("Added flush packet")
        
        app.logger.info(f"Total response size: {len(response)}")
        app.logger.info("=== End of Response ===\n")
        
        # Return response with proper headers
        headers = {
            'Content-Type': 'application/x-git-upload-pack-result',
            'Cache-Control': 'no-cache',
            'Expires': 'Fri, 01 Jan 1980 00:00:00 GMT',
            'Pragma': 'no-cache',
            'Connection': 'keep-alive'
        }
        return Response(bytes(response), headers=headers)
        
    except Exception as e:
        app.logger.error(f"Error in upload_pack: {str(e)}", exc_info=True)
        return str(e), 500

@app.route('/git-ls-files')
def ls_files():
    """List all files in the directory"""
    files = []
    for root, _, filenames in os.walk(TARGET_DIR):
        for filename in filenames:
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, TARGET_DIR)
            files.append(rel_path)
    
    return "\n".join(files) + "\n"

def parse_args():
    parser = argparse.ArgumentParser(description='GitDIR - Serve a directory as a git repository')
    parser.add_argument('--dir', '-d', 
                      default=os.getcwd(),
                      help='Directory to serve (default: current directory)')
    parser.add_argument('--port', '-p',
                      type=int,
                      default=5000,
                      help='Port to run the server on (default: 5000)')
    parser.add_argument('--host',
                      default='127.0.0.1',
                      help='Host to run the server on (default: 127.0.0.1)')
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_args()
    TARGET_DIR = os.path.abspath(args.dir)
    print(f"Serving directory: {TARGET_DIR}")
    app.run(host='127.0.0.1', port=5009, debug=True)
