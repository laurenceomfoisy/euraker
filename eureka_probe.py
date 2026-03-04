import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager


DEFAULT_START_URL = "https://acces.bibl.ulaval.ca/login?url=https://nouveau.eureka.cc/access/ip/default.aspx?un=ulaval1"


def setup_driver():
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )
    driver.implicitly_wait(10)
    return driver


def extract_doc_keys_from_html(page_source):
    patterns = [
        r"_docKeyList\s*=\s*(\[.+?\]);",
        r"var\s+_docKeyList\s*=\s*(\[.+?\]);",
        r"_docKeyList\s*=\s*(\[.*?\])",
        r"docKeyList\s*=\s*(\[.+?\]);",
        r'"docKeys":\s*(\[.+?\])',
    ]

    for pattern in patterns:
        match = re.search(pattern, page_source, re.DOTALL)
        if not match:
            continue
        try:
            payload = match.group(1).replace('\\"', '"').replace("\\n", "")
            parsed = json.loads(payload)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if str(x).strip()]
        except Exception:
            continue
    return []


def extract_doc_keys_from_links(driver):
    keys = []
    links = driver.find_elements(By.XPATH, "//a[contains(@href, 'docName=')]")
    for link in links:
        href = link.get_attribute("href") or ""
        match = re.search(r"docName=([^&]+)", href)
        if match:
            keys.append(match.group(1))
    return keys


def switch_to_frame_path(driver, frame_path):
    try:
        driver.switch_to.default_content()
        for idx in frame_path:
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
            if idx >= len(frames):
                return False
            driver.switch_to.frame(frames[idx])
        return True
    except Exception:
        return False


def collect_frame_paths(driver, max_depth=3):
    paths = [tuple()]

    def walk(path, depth):
        if depth >= max_depth:
            return
        if not switch_to_frame_path(driver, path):
            return
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
        for i in range(len(frames)):
            child = path + (i,)
            paths.append(child)
            walk(child, depth + 1)

    walk(tuple(), 0)
    return paths


def estimate_total_results_from_html(page_source):
    compact = re.sub(r"\s+", " ", page_source)
    patterns = [
        r"([0-9][0-9\s\.,]{0,12})\s+(?:results|resultats|résultats)\b",
        r"(?:results|resultats|résultats)\D{0,20}([0-9][0-9\s\.,]{0,12})",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, re.IGNORECASE)
        if not match:
            continue
        digits = re.sub(r"[^0-9]", "", match.group(1))
        if digits:
            try:
                value = int(digits)
                if value > 0:
                    return value
            except ValueError:
                pass
    return None


def snapshot_dom_contexts(driver):
    contexts = []
    for frame_path in collect_frame_paths(driver):
        if not switch_to_frame_path(driver, frame_path):
            continue

        html = driver.page_source
        keys_html = extract_doc_keys_from_html(html)
        keys_links = extract_doc_keys_from_links(driver)
        result = {
            "frame_path": list(frame_path),
            "doc_keys_from_html": len(keys_html),
            "doc_keys_from_links": len(keys_links),
            "estimated_total_results": estimate_total_results_from_html(html),
            "url": driver.current_url,
        }
        contexts.append(result)

    switch_to_frame_path(driver, tuple())
    contexts.sort(
        key=lambda x: max(x["doc_keys_from_html"], x["doc_keys_from_links"]),
        reverse=True,
    )
    return contexts


def parse_performance_logs(raw_logs):
    requests = {}
    for item in raw_logs:
        try:
            message = json.loads(item.get("message", "{}"))
            payload = message.get("message", {})
            method = payload.get("method")
            params = payload.get("params", {})

            if method == "Network.requestWillBeSent":
                request = params.get("request", {})
                url = request.get("url")
                if not url:
                    continue
                entry = requests.setdefault(
                    url,
                    {
                        "url": url,
                        "request_count": 0,
                        "resource_types": set(),
                        "methods": set(),
                        "statuses": set(),
                    },
                )
                entry["request_count"] += 1
                if request.get("method"):
                    entry["methods"].add(request.get("method"))
                if params.get("type"):
                    entry["resource_types"].add(params.get("type"))

            elif method == "Network.responseReceived":
                response = params.get("response", {})
                url = response.get("url")
                if not url:
                    continue
                entry = requests.setdefault(
                    url,
                    {
                        "url": url,
                        "request_count": 0,
                        "resource_types": set(),
                        "methods": set(),
                        "statuses": set(),
                    },
                )
                if response.get("status") is not None:
                    entry["statuses"].add(int(response["status"]))
                if params.get("type"):
                    entry["resource_types"].add(params.get("type"))
        except Exception:
            continue

    entries = []
    for value in requests.values():
        parsed = urlparse(value["url"])
        query = parse_qs(parsed.query)
        flat_query = {k: v[:2] for k, v in query.items()}
        entries.append(
            {
                "url": value["url"],
                "host": parsed.netloc,
                "path": parsed.path,
                "query_keys": sorted(query.keys()),
                "query_sample": flat_query,
                "request_count": value["request_count"],
                "resource_types": sorted(value["resource_types"]),
                "methods": sorted(value["methods"]),
                "statuses": sorted(value["statuses"]),
            }
        )

    entries.sort(key=lambda x: x["request_count"], reverse=True)
    return entries


def likely_results_endpoints(entries):
    keywords = [
        "result",
        "search",
        "query",
        "scroll",
        "document",
        "listing",
        "page",
        "offset",
        "cursor",
    ]
    filtered = []
    for entry in entries:
        text = (entry["path"] + " " + " ".join(entry["query_keys"])).lower()
        types = set(entry["resource_types"])
        type_match = bool(types.intersection({"XHR", "Fetch"}))
        keyword_match = any(k in text for k in keywords)
        if type_match and keyword_match:
            filtered.append(entry)
    return filtered


def main():
    output_dir = Path("./probe_reports").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    driver = setup_driver()
    try:
        print(f"Opening Eureka login URL:\n{DEFAULT_START_URL}\n", flush=True)
        driver.get(DEFAULT_START_URL)

        print("Manual step:", flush=True)
        print("1) Log in with your institution", flush=True)
        print("2) Run the query that shows 7383 results", flush=True)
        print("3) Scroll the infinite list for at least 20-30 seconds", flush=True)
        print("4) Return to this terminal and press Enter", flush=True)
        input("Press Enter when done interacting... ")

        print("Collecting browser performance logs...", flush=True)
        raw_logs = driver.get_log("performance")
        if len(raw_logs) > 20000:
            raw_logs = raw_logs[-20000:]
            print(
                "Using last 20,000 performance events for faster processing", flush=True
            )

        print(f"Parsing {len(raw_logs)} performance events...", flush=True)
        parsed_logs = parse_performance_logs(raw_logs)
        print(f"Parsed {len(parsed_logs)} unique request URLs", flush=True)

        candidates = likely_results_endpoints(parsed_logs)
        print(f"Found {len(candidates)} likely results endpoints", flush=True)

        print("Analyzing DOM/frame contexts...", flush=True)
        dom_contexts = snapshot_dom_contexts(driver)
        print(f"Collected {len(dom_contexts)} DOM contexts", flush=True)

        report = {
            "timestamp": stamp,
            "current_url": driver.current_url,
            "performance_log_count": len(raw_logs),
            "candidate_endpoint_count": len(candidates),
            "candidate_endpoints": candidates[:50],
            "top_requests": parsed_logs[:100],
            "dom_contexts": dom_contexts,
        }

        json_path = output_dir / f"eureka_probe_{stamp}.json"
        json_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8"
        )

        txt_path = output_dir / f"eureka_probe_{stamp}.txt"
        with txt_path.open("w", encoding="utf-8") as f:
            f.write("Eureka Probe Summary\n")
            f.write("====================\n")
            f.write(f"Current URL: {report['current_url']}\n")
            f.write(f"Performance entries: {report['performance_log_count']}\n")
            f.write(f"Candidate endpoints: {report['candidate_endpoint_count']}\n\n")

            f.write("Best DOM contexts (top 5)\n")
            for ctx in dom_contexts[:5]:
                max_keys = max(ctx["doc_keys_from_html"], ctx["doc_keys_from_links"])
                f.write(
                    f"- frame_path={ctx['frame_path']} keys_html={ctx['doc_keys_from_html']} "
                    f"keys_links={ctx['doc_keys_from_links']} max={max_keys} "
                    f"estimated_total={ctx['estimated_total_results']}\n"
                )

            f.write("\nCandidate endpoints (top 15)\n")
            for entry in candidates[:15]:
                f.write(
                    f"- {entry['url']} | reqs={entry['request_count']} | "
                    f"types={entry['resource_types']} | statuses={entry['statuses']}\n"
                )

        print("\nProbe completed.", flush=True)
        print(f"JSON report: {json_path}", flush=True)
        print(f"Text summary: {txt_path}", flush=True)
        print(
            "Share the JSON file contents (or key parts) and I will wire API-mode extraction.",
            flush=True,
        )

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
