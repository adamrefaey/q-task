#!/usr/bin/env python3
"""Download artifacts from a workflow run and merge coverage.xml files.

Usage: download_and_merge_artifacts.py <run_id> <owner/repo>

Requires env var `GITHUB_TOKEN` with permission to read workflow run artifacts.

The script downloads all artifacts attached to the specified run, extracts any
`coverage.xml` files, reads `lines-covered` and `lines-valid` attributes when
available and sums them to compute an overall coverage percentage. Falls back
to counting <line hits="..."> elements if attributes are missing.
"""

import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile


def api_get(url: str, token: str):
    # Some environments accept either 'token <token>' or 'Bearer <token>'.
    # Try both schemes if the first returns 401/403.
    last_err = None
    for scheme in ("token", "Bearer"):
        req = Request(url)
        req.add_header("Authorization", f"{scheme} {token}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        try:
            with urlopen(req) as resp:
                return json.load(resp)
        except HTTPError as e:
            if e.code in (401, 403):
                # Try the next scheme
                last_err = e
                continue
            raise
    # If both schemes failed, re-raise the last auth error if present,
    # otherwise raise a clear runtime error so callers do not see an
    # unbound variable. This shouldn't normally happen because failures
    # will raise HTTPError above, but guard defensively.
    if last_err is not None:
        raise last_err
    raise RuntimeError("api_get: no response and no HTTPError encountered")


def download_url(url: str, token: str, dest: Path):
    # When downloading artifact archives GitHub may redirect the request
    # to a storage provider (S3, Azure, etc.). Those hosts may reject an
    # Authorization header intended for the GitHub API, resulting in a 403
    # like: "Server failed to authenticate the request". To avoid this we
    # perform the initial request with the Authorization header and follow
    # redirects manually: if the response is a redirect, perform the final
    # GET without the Authorization header.
    # Try 'token' then 'Bearer' authorization schemes for the initial request.
    last_err = None
    for scheme in ("token", "Bearer"):
        req = Request(url)
        req.add_header("Authorization", f"{scheme} {token}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        try:
            with urlopen(req) as resp, open(dest, "wb") as out:
                out.write(resp.read())
                return
        except HTTPError as e:
            last_err = e
            # If redirect-like response, follow location without auth.
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get("Location")
                if not loc:
                    raise
                req2 = Request(loc)
                req2.add_header("Accept", "application/octet-stream")
                with urlopen(req2) as resp2, open(dest, "wb") as out:
                    out.write(resp2.read())
                    return
            # For auth failures, try next scheme
            if e.code in (401, 403):
                continue
            raise
    # If we get here, both auth schemes failed without a redirect fallback
    if last_err:
        # If 403/401, raise to allow caller to provide guidance
        raise last_err


def parse_root_counts(path: Path):
    # return (covered, valid) or None if not present
    try:
        import xml.etree.ElementTree as ET

        tree = ET.parse(path)
        root = tree.getroot()
        # coverage.py / cobertura style root attrs
        covered = root.attrib.get("lines-covered") or root.attrib.get("lines_covered")
        valid = root.attrib.get("lines-valid") or root.attrib.get("lines_valid")
        if covered is not None and valid is not None:
            return int(covered), int(valid)
        # sometimes line-rate present; try to use lines-valid if available
        lr = root.attrib.get("line-rate") or root.attrib.get("line_rate")
        if lr is not None and (
            valid := root.attrib.get("lines-valid") or root.attrib.get("lines_valid")
        ):
            try:
                v = float(lr)
                return int(float(valid) * v), int(valid)
            except Exception:
                pass
    except Exception:
        return None
    return None


def fallback_count(path: Path):
    # Count <line hits="..."> occurrences
    try:
        import xml.etree.ElementTree as ET

        tree = ET.parse(path)
        root = tree.getroot()
        total = 0
        covered = 0
        for elem in root.iter():
            if elem.tag.lower().endswith("line") and "hits" in elem.attrib:
                total += 1
                try:
                    if int(elem.attrib.get("hits", "0")) > 0:
                        covered += 1
                except Exception:
                    pass
        return covered, total
    except Exception:
        return 0, 0


def main(argv):
    if len(argv) < 3:
        print("Usage: download_and_merge_artifacts.py <run_id> <owner/repo>", file=sys.stderr)
        return 2
    run_id = argv[1]
    repo = argv[2]
    # Prefer the automatically provided GITHUB_TOKEN. Fall back to a
    # repository secret `ARTIFACT_DOWNLOAD_TOKEN` (a PAT) if present. Do not
    # accidentally print tokens to logs.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("ARTIFACT_DOWNLOAD_TOKEN")
    if not token:
        print("No GITHUB_TOKEN or ARTIFACT_DOWNLOAD_TOKEN found in environment", file=sys.stderr)
        print(
            "Ensure the workflow provides a token with permissions to read artifacts",
            file=sys.stderr,
        )
        return 2
    # Detect which env var is being used for clearer guidance (without exposing token)
    used_token_env = (
        "GITHUB_TOKEN"
        if os.environ.get("GITHUB_TOKEN")
        else ("ARTIFACT_DOWNLOAD_TOKEN" if os.environ.get("ARTIFACT_DOWNLOAD_TOKEN") else "")
    )
    if used_token_env:
        print(f"Using token from {used_token_env}", file=sys.stderr)

    owner, repo_name = repo.split("/", 1)
    artifacts_api = (
        f"https://api.github.com/repos/{owner}/{repo_name}/actions/runs/{run_id}/artifacts"
    )
    # Simple retry/backoff for transient errors when querying artifacts
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            data = api_get(artifacts_api, token)
            break
        except HTTPError as e:
            print(
                f"Attempt {attempt} failed querying artifacts: HTTP {e.code} {e.reason}",
                file=sys.stderr,
            )
            if e.code in (401, 403):
                print(
                    "Token may be missing permissions (need 'actions:read' or repo scope for PAT).",
                    file=sys.stderr,
                )
                if attempt >= max_attempts:
                    raise
                # do not retry auth failures immediately; wait a bit then retry
            elif 500 <= e.code < 600 and attempt < max_attempts:
                import time

                time.sleep(2**attempt)
                continue
            else:
                raise
    else:
        print("Failed to retrieve artifacts after retries", file=sys.stderr)
        return 2
    artifacts = data.get("artifacts", [])
    if not artifacts:
        print("No artifacts found", file=sys.stderr)
        print("unknown")
        return 0

    tmpdir = Path(tempfile.mkdtemp())
    collected = []
    for art in artifacts:
        url = art.get("archive_download_url")
        if not url:
            continue
        dest = tmpdir / f"artifact-{art['id']}.zip"
        # Retry downloads as well — storage endpoints may transiently reject
        for attempt in range(1, 4):
            try:
                download_url(url, token, dest)
                break
            except HTTPError as e:
                print(
                    f"Download attempt {attempt} for artifact {art['id']} failed: HTTP {e.code}",
                    file=sys.stderr,
                )
                if attempt >= 3:
                    raise
                import time

                time.sleep(2**attempt)
        try:
            with zipfile.ZipFile(dest, "r") as z:
                for name in z.namelist():
                    if name.endswith("coverage.xml") or name.endswith("/coverage.xml"):
                        outpath = tmpdir / f"{art['id']}-{Path(name).name}"
                        z.extract(name, tmpdir)
                        extracted = tmpdir / name
                        # move to top-level to simplify path
                        extracted.rename(outpath)
                        collected.append(outpath)
        except zipfile.BadZipFile:
            continue

    # If no coverage.xml files found inside artifacts, try to see if artifact names themselves are coverage.xml
    if not collected:
        # Some workflows may upload coverage.xml directly (artifact name)
        for art in artifacts:
            if art.get("name", "").startswith("coverage"):
                url = art.get("archive_download_url")
                dest = tmpdir / f"artifact-{art['id']}.zip"
                download_url(url, token, dest)
                try:
                    with zipfile.ZipFile(dest, "r") as z:
                        for name in z.namelist():
                            if name.endswith("coverage.xml"):
                                outpath = tmpdir / f"{art['id']}-{Path(name).name}"
                                z.extract(name, tmpdir)
                                extracted = tmpdir / name
                                extracted.rename(outpath)
                                collected.append(outpath)
                except zipfile.BadZipFile:
                    continue

    if not collected:
        print("No coverage.xml files found in artifacts", file=sys.stderr)
        print("unknown")
        return 0

    total_covered = 0
    total_valid = 0
    for c in collected:
        counts = parse_root_counts(c)
        if counts is None:
            counts = fallback_count(c)
        covered, valid = counts
        total_covered += covered
        total_valid += valid

    if total_valid == 0:
        print("unknown")
        return 0
    pct = total_covered / total_valid
    print(f"{round(pct * 100)}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
