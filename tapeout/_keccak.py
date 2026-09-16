"""Minimal, dependency-free Keccak-256 (Ethereum's keccak -- NOT NIST SHA3,
which uses different padding) so that tapeout/verify.py's ABI discovery
(recovering unverified contract function selectors) does not require web3.py
or pycryptodome, neither of which is in requirements.txt.

Independent implementation from the public Keccak-f[1600] specification
(Bertoni, Daemen, Peeters, Van Assche), not derived from any TapeOut- or
BruceBlue-project-specific source -- this is generic, general-purpose
cryptography with no relationship to any circuit design.
"""

_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_ROT = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]
_MASK = (1 << 64) - 1


def _rol(x: int, n: int) -> int:
    n %= 64
    return ((x << n) | (x >> (64 - n))) & _MASK


def _keccak_f(state):
    for rnd in range(24):
        c = [state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x][y] ^= d[x]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(state[x][y], _ROT[x][y])
        for x in range(5):
            for y in range(5):
                state[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & _MASK & b[(x + 2) % 5][y])
        state[0][0] ^= _RC[rnd]
    return state


def keccak256(data: bytes) -> bytes:
    rate = 136  # bytes, for 256-bit output (1088-bit rate)
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    state = [[0] * 5 for _ in range(5)]
    for off in range(0, len(padded), rate):
        block = padded[off : off + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(block[i * 8 : i * 8 + 8], "little")
            x, y = i % 5, i // 5
            state[x][y] ^= lane
        state = _keccak_f(state)

    out = bytearray()
    while len(out) < 32:
        for i in range(rate // 8):
            x, y = i % 5, i // 5
            out += state[x][y].to_bytes(8, "little")
            if len(out) >= 32:
                break
        if len(out) < 32:
            state = _keccak_f(state)
    return bytes(out[:32])


def selector(signature: str) -> str:
    """4-byte Solidity function selector (hex, no 0x) for an ABI signature
    like 'transfer(address,uint256)'."""
    return keccak256(signature.encode()).hex()[:8]
