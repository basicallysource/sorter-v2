def pickMenu(options: list[str]) -> int | None:
    for i, option in enumerate(options):
        print(f"  [{i + 1}] {option}")
    try:
        raw = input("> ").strip()
    except (KeyboardInterrupt, EOFError):
        return None
    if not raw.isdigit():
        return None
    choice = int(raw) - 1
    if choice < 0 or choice >= len(options):
        return None
    return choice
