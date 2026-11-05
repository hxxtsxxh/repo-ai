def wrap_words(text, width):
    """Greedy word wrap: return a list of lines, each at most `width` characters.

    Words longer than `width` are placed alone on their own line, unbroken.
    Runs of whitespace between words collapse to one space; empty input gives [].
    """
    lines, current = [], ""
    for word in text.split(" "):
        if len(current) + len(word) <= width:
            current += word + " "
        else:
            lines.append(current)
            current = word + " "
    lines.append(current)
    return lines
