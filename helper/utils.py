def format_size(size):
    try:
        size = float(size)
    except (TypeError, ValueError):
        return str(size)
    if size <= 0:
        return "0"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return "{:.2f} {}".format(size, units[i])
