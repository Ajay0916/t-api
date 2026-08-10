def clean_results(resp):
    """Remove keys with None values from each result item.

    WZML-X checks for the presence of the "torrent"/"magnet" keys, so a
    value of None would render a broken button. Dropping None-valued keys
    keeps the response compatible.
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
        cleaned.append(item)
    resp["data"] = cleaned
    return resp
