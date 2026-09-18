"""Blob-endpoint transport for the reference zone, authenticated with a managed identity.

Large artifacts are staged as blocks so memory stays bounded and a new blob is created in one
commit. Overwrites are not attempted: an immutable container rejects them, which is the behaviour
the reference zone depends on.
"""

import base64
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree

API_VERSION = "2022-11-02"
BLOCK_ID_WIDTH = 8


class BlobTransport:
    def __init__(self, account, container, token, suffix="core.windows.net"):
        self._base = f"https://{account}.blob.{suffix}/{container}"
        self._token = token

    def _request(self, method, url, extra=None, body=None):
        request = urllib.request.Request(url, method=method, data=body)
        request.add_header("Authorization", "Bearer " + self._token)
        request.add_header("x-ms-version", API_VERSION)
        for key, value in (extra or {}).items():
            request.add_header(key, value)
        return urllib.request.urlopen(request, timeout=600)

    def _url(self, path, query=""):
        quoted = urllib.parse.quote(path)
        return f"{self._base}/{quoted}{query}"

    def uri(self, path):
        return self._url(path)

    def exists(self, path):
        try:
            self._request("HEAD", self._url(path)).close()
            return True
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return False
            raise

    def get(self, path):
        with self._request("GET", self._url(path)) as response:
            return response.read()

    def put_bytes(self, path, payload):
        self._request("PUT", self._url(path), {
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": "application/json",
        }, payload).close()

    def put(self, path, chunks):
        block_ids = []
        for index, chunk in enumerate(chunks):
            block_id = base64.b64encode(str(index).zfill(BLOCK_ID_WIDTH).encode()).decode()
            self._request("PUT", self._url(path, "?comp=block&blockid="
                                           + urllib.parse.quote(block_id)), body=chunk).close()
            block_ids.append(block_id)

        blocks = "".join(f"<Latest>{block_id}</Latest>" for block_id in block_ids)
        document = ("<?xml version='1.0' encoding='utf-8'?><BlockList>"
                    f"{blocks}</BlockList>").encode()
        self._request("PUT", self._url(path, "?comp=blocklist"), {
            "Content-Type": "application/xml",
        }, document).close()

    def list(self, prefix):
        paths = []
        marker = ""
        while True:
            query = ("?restype=container&comp=list&prefix=" + urllib.parse.quote(prefix)
                     + (f"&marker={urllib.parse.quote(marker)}" if marker else ""))
            with self._request("GET", f"{self._base}{query}") as response:
                listing = ElementTree.fromstring(response.read())
            paths.extend(blob.findtext("Name") for blob in listing.iter("Blob"))
            marker = listing.findtext("NextMarker") or ""
            if not marker:
                return paths
