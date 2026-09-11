"""Inventory an Azure Files landing share over its REST data plane.

Applies the same completeness rule as the local scanner. Azure Files exposes change time at
100-nanosecond resolution, which the stability comparison uses in place of local mtime.
"""

import argparse
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from scripts.scan_landing import DEFAULT_PATTERN, evaluate_inventory, local_path

API_VERSION = "2022-11-02"
IMDS = "http://169.254.169.254/metadata/identity/oauth2/token"


def managed_identity_token(client_id, resource="https://storage.azure.com/"):
    query = urllib.parse.urlencode({
        "api-version": "2018-02-01", "resource": resource, "client_id": client_id,
    })
    request = urllib.request.Request("%s?%s" % (IMDS, query), headers={"Metadata": "true"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["access_token"]


def _send(method, url, token):
    request = urllib.request.Request(url, method=method)
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("x-ms-version", API_VERSION)
    request.add_header("x-ms-file-request-intent", "backup")
    return urllib.request.urlopen(request, timeout=60)


def _change_time_ns(headers):
    precise = headers.get("x-ms-file-change-time")
    if precise:
        return int(datetime.fromisoformat(precise.replace("Z", "+00:00")).timestamp() * 1_000_000_000)
    modified = headers.get("Last-Modified")
    if not modified:
        raise ValueError("Azure Files returned no change or modification time.")
    return int(parsedate_to_datetime(modified).timestamp() * 1_000_000_000)


def list_share(account, share, token, directory=""):
    """Yield (relative path, size, change time) for every file beneath a share directory."""
    base = "https://%s.file.core.windows.net/%s" % (account, share)
    url = "%s/%s?restype=directory&comp=list" % (base, urllib.parse.quote(directory))
    with _send("GET", url, token) as response:
        listing = ElementTree.fromstring(response.read())

    for entry in listing.find("Entries") or []:
        name = entry.findtext("Name")
        relative = "%s/%s" % (directory, name) if directory else name
        if entry.tag == "Directory":
            yield from list_share(account, share, token, relative)
            continue
        with _send("HEAD", "%s/%s" % (base, urllib.parse.quote(relative)), token) as properties:
            headers = properties.headers
        yield relative, int(headers["Content-Length"]), _change_time_ns(headers)


def scan_share(account, share, inventory, client_id, pattern=DEFAULT_PATTERN,
               completion_marker=None, token=None):
    inventory = local_path(inventory)
    token = token or managed_identity_token(client_id)
    matcher = re.compile(pattern)
    if not {"run_id", "sample_id"}.issubset(matcher.groupindex):
        raise ValueError("Path pattern requires named run_id and sample_id groups.")

    observed_at = datetime.now(timezone.utc).isoformat()
    observations = []
    for relative, size, change_time_ns in sorted(list_share(account, share, token)):
        match = matcher.fullmatch(relative)
        parsed = bool(match and match.group("run_id") and match.group("sample_id"))
        observations.append((
            relative,
            match.group("run_id") if parsed else None,
            match.group("sample_id") if parsed else None,
            size, change_time_ns, observed_at, observed_at,
            None if parsed else "unrecognized-path",
        ))

    return evaluate_inventory(
        observations, inventory, "https://%s.file.core.windows.net/%s" % (account, share),
        pattern, completion_marker, observed_at, mode="azure-files",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--share", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--pattern", default=DEFAULT_PATTERN)
    parser.add_argument("--completion-marker")
    arguments = parser.parse_args()

    report = scan_share(
        arguments.account, arguments.share, arguments.inventory, arguments.client_id,
        arguments.pattern, arguments.completion_marker,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
