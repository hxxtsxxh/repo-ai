def format_money(cents):
    """Format whole cents as a dollar string such as '$12.05'."""
    return "$%d.%d" % (cents // 100, cents % 100)
