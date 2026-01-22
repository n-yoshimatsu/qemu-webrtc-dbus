# Performance Investigation History

This directory contains the historical investigation documents tracking the root cause analysis of the DMA-BUF tiling format issue.

## Document Timeline

### v1 (2026-01-20 09:35) - Initial Investigation
- **File**: `Performance_Issue_v1.md`
- **Focus**: Basic performance measurements and initial hypotheses
- **Key Findings**: High latency in frame capture, UnixFD transfer issues suspected

### v2 (2026-01-20 14:42) - D-Bus Protocol Analysis
- **File**: `Performance_Issue_v2.md`
- **Focus**: Deep dive into D-Bus message handling
- **Key Findings**: Message filter timing, UnixFDList handling

### v3 (2026-01-20 23:57) - P2P Connection Investigation
- **File**: `Performance_Issue_v3.md`
- **Focus**: P2P D-Bus connection establishment
- **Key Findings**: Direct connection vs session bus, capability negotiation

### v4 (2026-01-21 18:26) - RGB Conversion Optimization
- **File**: `Performance_Issue_v4.md`
- **Focus**: Stride handling and RGB conversion performance
- **Key Findings**: NumPy optimization reduced conversion time from 500ms to 10ms

### v5 (2026-01-22 09:22) - Root Cause Identification
- **File**: `Performance_Issue_v5.md` (also in project root)
- **Focus**: DMA-BUF tiling format investigation
- **Key Findings**: 
  - DMA-BUF modifier value indicates tiled memory layout
  - CPU cannot directly read tiled format
  - gl=off (Scanout/linear) works correctly
  - OpenGL implementation required for gl=on (DMA-BUF/tiled)

## Investigation Evolution

The investigation evolved through several phases:

1. **Performance Symptoms** → High frame capture latency
2. **Protocol Analysis** → D-Bus message handling optimized
3. **Connection Architecture** → P2P connection established with UnixFD support
4. **Data Processing** → RGB conversion optimized with NumPy
5. **Root Cause** → Tiled memory format requires OpenGL decoding

## Current Status

- ✅ Problem identified: DMA-BUF tiling format (modifier: 0x0100000000000002)
- ✅ Workaround verified: gl=off mode works (8.6ms/frame)
- 🚧 Solution in progress: OpenGL DMA-BUF implementation

## References

See the main `Performance_Issue_v5.md` in the project root for the most current and comprehensive analysis.
