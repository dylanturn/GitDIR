# GitDIR

GitDIR is a Python Flask API that allows you to interact with a filesystem directory as if it were a GIT repository over HTTPS.

## Features

- Pure Python implementation (no git client dependency)
- Full Git Smart HTTP protocol support
- Proper object and packfile formats
- Efficient object caching
- Reference and capability negotiation

## Setup and Installation

1. The project uses a Python virtual environment located at `./venv`
2. Install dependencies using:
```bash
./venv/bin/pip install -r requirements.txt
```

## Supported Commands

- `git clone`: Downloads the directory into the current directory.
- `git ls-files`: Lists the files in the directory.

## Usage

Start the API server with default settings (serves current directory on localhost:5000):
```bash
./venv/bin/python gitdir.py
```

### Configuration Options

The server can be configured with the following command-line arguments:

- `--dir` or `-d`: Directory to serve (default: current directory)
- `--port` or `-p`: Port to run the server on (default: 5000)
- `--host`: Host to run the server on (default: 127.0.0.1)
- `--debug`: Enable debug mode for development

Example with custom configuration:
```bash
./venv/bin/python gitdir.py --dir /path/to/directory --port 8080 --host 0.0.0.0 --debug
```

## Implementation Details

### Git Objects
- Blob objects for file content
- Tree objects for directory structure
- Commit objects with proper metadata
- SHA-1 based content addressing

### Protocol Support
- Smart HTTP protocol
- Reference advertisement
- Packfile generation
- Side-band-64k progress reporting

### Architecture
The codebase follows clean architecture principles:
1. Core Git functionality:
   - Object creation and storage
   - Packfile generation
   - Reference management
2. HTTP layer:
   - Protocol handling
   - Content negotiation
   - Error handling

## Development Guidelines

Before making any changes to the codebase:
1. Review `STANDARDS.md` for project coding standards and guidelines
2. Check `REGRESSIONS.md` to ensure changes don't break existing functionality
3. Consider:
   - Potential code duplication
   - Integration with existing codebase
   - Potential limitations or issues
4. Document changes in `CHECKPOINTS.md`

For detailed information about the project structure and development process, refer to:
- `git-http-protocol.md`: Git protocol implementation details
- `CHECKPOINTS.md`: Change tracking and project history
