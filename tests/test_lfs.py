"""Strict git-LFS pointer parsing + verification (hills 0.12)."""

import hashlib

import pytest

from hills.errors import LfsError
from hills.lfs import LfsPointer, parse_pointer, verify_object


def _pointer_bytes(oid: str, size: int) -> bytes:
    # canonical: version first, then keys alphabetically, LF-terminated
    return f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {size}\n".encode()


def test_parse_valid_pointer():
    oid = "a" * 64
    p = parse_pointer(_pointer_bytes(oid, 1234))
    assert p == LfsPointer(oid=oid, size=1234)


def test_non_pointer_returns_none():
    assert parse_pointer(b"") is None
    assert parse_pointer(b"just some file contents\n") is None
    assert parse_pointer(b"\x00\x01\x02 binary") is None
    assert parse_pointer(b"x" * 5000) is None  # too big to be a pointer


def test_extension_pointer_rejected():
    oid = "b" * 64
    data = (
        f"version https://git-lfs.github.com/spec/v1\n"
        f"ext-0-foo sha256:{'c'*64}\noid sha256:{oid}\nsize 10\n"
    ).encode()
    with pytest.raises(LfsError, match="extension"):
        parse_pointer(data)


def test_malformed_pointer_raises():
    # declares the version but has a bad oid
    with pytest.raises(LfsError):
        parse_pointer(b"version https://git-lfs.github.com/spec/v1\noid sha256:xyz\nsize 10\n")
    # bad size
    with pytest.raises(LfsError):
        parse_pointer(
            f"version https://git-lfs.github.com/spec/v1\noid sha256:{'a'*64}\nsize NaN\n".encode()
        )
    # unknown key
    with pytest.raises(LfsError, match="unexpected keys"):
        parse_pointer(
            f"version https://git-lfs.github.com/spec/v1\noid sha256:{'a'*64}\nsize 1\nx y\n".encode()
        )
    # duplicate key
    with pytest.raises(LfsError, match="duplicate"):
        parse_pointer(
            f"version https://git-lfs.github.com/spec/v1\noid sha256:{'a'*64}\noid sha256:{'b'*64}\nsize 1\n".encode()
        )


def test_verify_object_accepts_matching_bytes(tmp_path):
    data = b"the real dataset bytes"
    oid = hashlib.sha256(data).hexdigest()
    f = tmp_path / "data.bin"
    f.write_bytes(data)
    verify_object(f, LfsPointer(oid=oid, size=len(data)))  # no raise


def test_verify_object_rejects_size_mismatch(tmp_path):
    data = b"abc"
    f = tmp_path / "d"
    f.write_bytes(data)
    with pytest.raises(LfsError, match="size"):
        verify_object(f, LfsPointer(oid=hashlib.sha256(data).hexdigest(), size=999))


def test_verify_object_rejects_unresolved_pointer(tmp_path):
    # the file still holds the pointer text, not the content -> sha256 mismatch
    oid = "d" * 64
    ptr = _pointer_bytes(oid, 100)
    f = tmp_path / "d"
    f.write_bytes(ptr)
    with pytest.raises(LfsError, match="size|sha256"):
        verify_object(f, LfsPointer(oid=oid, size=100))


def test_verify_object_rejects_symlink(tmp_path):
    data = b"x"
    real = tmp_path / "real"
    real.write_bytes(data)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(LfsError, match="regular file"):
        verify_object(link, LfsPointer(oid=hashlib.sha256(data).hexdigest(), size=1))
