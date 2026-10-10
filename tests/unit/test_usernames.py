from watch_party.domain.usernames import sanitize_username, unique_username


def test_sanitize_strips_control_characters() -> None:
    assert sanitize_username("ay\x00ush\n") == "ayush"


def test_sanitize_trims_and_truncates() -> None:
    assert sanitize_username("   Ayush   ") == "Ayush"
    assert len(sanitize_username("x" * 100)) == 24
    assert sanitize_username("   ") == "user"


def test_unique_username_collision_suffixes() -> None:
    taken = ["akshay"]
    assert unique_username("akshay", taken) == "akshay#2"
    assert unique_username("akshay", ["akshay", "akshay#2"]) == "akshay#3"


def test_unique_username_case_insensitive() -> None:
    assert unique_username("Akshay", ["AKSHAY"]) == "Akshay#2"


def test_unique_username_when_free() -> None:
    assert unique_username("neha", []) == "neha"
