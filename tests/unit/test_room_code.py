from watch_party.domain.room_code import CODE_ALPHABET, CODE_LENGTH, generate_room_code


def test_code_shape() -> None:
    code = generate_room_code()
    assert len(code) == CODE_LENGTH
    assert set(code) <= set(CODE_ALPHABET)


def test_code_avoids_ambiguous_characters() -> None:
    for ambiguous in "01OIL":
        assert ambiguous not in CODE_ALPHABET


def test_codes_are_random() -> None:
    codes = {generate_room_code() for _ in range(200)}
    # 31^6 possibilities: 200 draws should (essentially) never collide.
    assert len(codes) > 190
