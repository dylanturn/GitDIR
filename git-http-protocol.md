# Git HTTP Protocol Documentation

## Overview

Git supports two HTTP-based protocols for client-server communication:
1. **Dumb HTTP Protocol** - A simple, read-only protocol
2. **Smart HTTP Protocol** - A bidirectional protocol supporting full Git functionality

## Dumb HTTP Protocol

The dumb protocol is a simple, read-only protocol that serves Git repository contents as static files.

### Endpoints:
- `GET /info/refs` - Lists all references (branches, tags)
- `GET /objects/xx/xxxxxxx` - Retrieves loose objects
- `GET /objects/pack/pack-*.pack` - Downloads packfiles
- `GET /objects/pack/pack-*.idx` - Downloads packfile indices

### Characteristics:
- No server-side Git intelligence
- Client must do all computation
- Higher network overhead
- Read-only access

## Smart HTTP Protocol

The smart protocol enables bidirectional communication and is the modern standard.

### Discovery

1. Client initiates with:
```
GET /info/refs?service=git-upload-pack
```

2. Server responds with:
- Content-Type: application/x-git-upload-pack-advertisement
- PKT-LINE formatted data:
  ```
  001e# service=git-upload-pack\n
  0000
  <capabilities and refs in PKT-LINE format>
  ```

### Upload-Pack (Clone/Fetch)

1. Client requests:
```
POST /git-upload-pack
Content-Type: application/x-git-upload-pack-request
```

2. Server responds with:
- Content-Type: application/x-git-upload-pack-result
- Packfile data containing requested objects

### PKT-LINE Format

- 4-digit hex length prefix (including prefix itself)
- Length 0000 indicates flush packet
- Example:
  ```
  001e# service=git-upload-pack\n  # length: 30 (0x001e)
  0000                            # flush packet
  ```

## Implementation Requirements

For a basic read-only Git server (our use case):

1. Required Endpoints:
   - `/info/refs?service=git-upload-pack`
   - `/git-upload-pack`

2. Required Functionality:
   - Proper Content-Type headers
   - PKT-LINE formatting
   - Basic packfile generation
   - Reference advertisement

3. Minimum Capabilities:
   - multi_ack_detailed
   - thin-pack
   - side-band
   - side-band-64k

## Security Considerations

1. Input Validation:
   - Validate all client inputs
   - Sanitize path components
   - Prevent directory traversal

2. Resource Protection:
   - Rate limiting
   - Maximum pack size limits
   - Timeout controls