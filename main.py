"""Terminal entry point for the X keyword crawler."""

from __future__ import annotations

import asyncio

from config import CSV_PATH, JSON_PATH, ensure_directories, load_credentials
from crawler import AuthenticationError, XKeywordCrawler
from utils import save_results


def prompt_inputs() -> tuple[str, str, int]:
    while True:
        keyword = input("검색 키워드 입력: ").strip()
        if keyword:
            break
        print("[ERROR] 검색 키워드는 비워둘 수 없습니다")

    print("1. Latest\n2. Top")
    while True:
        choice = input("검색 방식 선택 [1]: ").strip() or "1"
        if choice in {"1", "2"}:
            product = "Latest" if choice == "1" else "Top"
            break
        print("[ERROR] 1 또는 2를 입력해 주세요")

    while True:
        raw_count = input("최대 수집 개수 [100]: ").strip() or "100"
        try:
            max_count = int(raw_count)
            if max_count > 0:
                break
        except ValueError:
            pass
        print("[ERROR] 최대 수집 개수는 1 이상의 정수여야 합니다")
    return keyword, product, max_count


async def crawl(keyword: str, product: str, max_count: int) -> None:
    crawler = XKeywordCrawler(load_credentials())
    try:
        await crawler.authenticate()
        await crawler.run(keyword, product, max_count)
    except AuthenticationError as error:
        print(f"[ERROR] {error}")
    except asyncio.CancelledError:
        print("\n[STOP] 사용자가 수집을 중단했습니다")
        raise
    except Exception as error:
        print(f"[ERROR] 수집 중 오류가 발생했습니다: {crawler._error_text(error)}")
    finally:
        try:
            save_results(crawler.results, CSV_PATH, JSON_PATH)
            print("\n[DONE]")
            print(f"총 수집: {len(crawler.results)}")
            print(f"CSV: {CSV_PATH.relative_to(CSV_PATH.parent.parent)}")
            print(f"JSON: {JSON_PATH.relative_to(JSON_PATH.parent.parent)}")
        except Exception as error:
            print(f"[ERROR] 결과 저장 실패: {crawler._error_text(error)}")


def main() -> None:
    ensure_directories()
    print("=" * 40)
    print("X Keyword Crawler")
    print("=" * 40)
    keyword, product, max_count = prompt_inputs()
    print(f"\n검색어: {keyword}")
    print(f"검색 방식: {product}")
    print(f"최대 수집: {max_count}\n")
    try:
        asyncio.run(crawl(keyword, product, max_count))
    except KeyboardInterrupt:
        # The coroutine's finally block saves all records before this is reached.
        print("[STOP] 프로그램을 종료합니다")


if __name__ == "__main__":
    main()
