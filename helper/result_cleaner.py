def clean_results(resp):
    """Remove keys with None values from each result item.

    WZML-X checks for the presence of the "torrent"/"magnet" keys, so a
    value of None would render a broken button. Dropping None-valued keys
    keeps the response compatible. The "size" key is always kept (empty
    string when missing) so WZML-X never aborts rendering a result after
    its title line.
    """
    if not isinstance(resp, dict):
        return resp
    data = resp.get("data")
    if not isinstance(data, list):
        return resp
    cleaned = []
    for item in data:
        if isinstance(item, dict):
            item = {k: v for k, v in item.items() if v is not None}
            if "size" not in item:
                item["size"] = ""
        cleaned.append(item)
    resp["data"] = cleaned
    return resp
