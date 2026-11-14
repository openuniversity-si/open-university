"""Ed25519 signature verification (RFC 8032 §5.1.7), in the standard library only, for the forge's webhooks (P4 F2b):
Origin signs each delivery with Ed25519, and neither the gate's Python nor the service's image carries a library for it.

verify(public_key, message, signature) answers whether the 64-byte signature of the message verifies under the
32-byte public key, by the reference algorithm of RFC 8032 §6: decode A and R as points (refusing a non-canonical or
off-curve encoding), refuse S >= L, and check [S]B = R + [SHA-512(R || A || M)]A. It verifies public data only (the
signature, the message and the key are all public), so a timing difference reveals nothing. sign(secret, message) is
RFC 8032 §5.1.6, for the tests and local tools only (the service never signs). Both are tested against the RFC's own
vectors, and verify against signatures from an independent implementation.
"""
import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def inverse(x):
    return pow(x, P - 2, P)


def recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * inverse(D * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


G_Y = 4 * inverse(5) % P
G_X = recover_x(G_Y, 0)
BASE = (G_X, G_Y, 1, G_X * G_Y % P)  # extended homogeneous coordinates (X, Y, Z, T)
NEUTRAL = (0, 1, 1, 0)


def add(p, q):
    a, b = (p[1] - p[0]) * (q[1] - q[0]) % P, (p[1] + p[0]) * (q[1] + q[0]) % P
    c, d = 2 * p[3] * q[3] * D % P, 2 * p[2] * q[2] % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return e * f % P, g * h % P, f * g % P, e * h % P


def multiply(scalar, point):
    found = NEUTRAL
    while scalar > 0:
        if scalar & 1:
            found = add(found, point)
        point = add(point, point)
        scalar >>= 1
    return found


def equal(p, q):
    return (p[0] * q[2] - q[0] * p[2]) % P == 0 and (p[1] * q[2] - q[1] * p[2]) % P == 0


def decompress(encoded):
    if len(encoded) != 32:
        return None
    y = int.from_bytes(encoded, 'little')
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def compress(point):
    z = inverse(point[2])
    x, y = point[0] * z % P, point[1] * z % P
    return (y | ((x & 1) << 255)).to_bytes(32, 'little')


def expanded(secret):
    """A 32-byte secret's scalar and prefix (RFC 8032 §5.1.5)."""
    hashed = hashlib.sha512(secret).digest()
    scalar = int.from_bytes(hashed[:32], 'little') & ((1 << 254) - 8) | (1 << 254)
    return scalar, hashed[32:]


def public_key(secret):
    return compress(multiply(expanded(secret)[0], BASE))


def sign(secret, message):
    scalar, prefix = expanded(secret)
    public = compress(multiply(scalar, BASE))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), 'little') % L
    encoded = compress(multiply(r, BASE))
    k = int.from_bytes(hashlib.sha512(encoded + public + message).digest(), 'little') % L
    return encoded + ((r + k * scalar) % L).to_bytes(32, 'little')


def verify(public_key, message, signature):
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a, r = decompress(public_key), decompress(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], 'little')
    if s >= L:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), 'little') % L
    return equal(multiply(s, BASE), add(r, multiply(h, a)))
