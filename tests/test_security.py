from yasno.security import derive_key, sign_token, verify_token

KEY = derive_key("bot-token", "parent")


def test_tokens_roundtrip_for_many_subjects() -> None:
    for subject in range(1, 2000):
        token = sign_token(KEY, subject, 60, now=1_790_000_000 + subject)
        assert verify_token(KEY, token, now=1_790_000_000) == subject


def test_tampered_token_is_rejected() -> None:
    token = sign_token(KEY, 42, 60, now=1_790_000_000)
    forged = token.replace("42_", "43_", 1)
    assert verify_token(KEY, forged, now=1_790_000_000) is None
    assert verify_token(derive_key("other", "parent"), token, now=1_790_000_000) is None


def test_expired_token_is_rejected() -> None:
    token = sign_token(KEY, 42, 60, now=1_790_000_000)
    assert verify_token(KEY, token, now=1_790_000_061) is None
