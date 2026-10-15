import httpx
import pytest

from ao3reader.fetch import FetchError, fetch_work, parse_work_id


@pytest.mark.parametrize(
    "ref",
    [
        "987654",
        "https://archiveofourown.org/works/987654",
        "https://archiveofourown.org/works/987654/chapters/111?view_adult=true#workskin",
        "archiveofourown.org/collections/fest/works/987654",
        "  https://archiveofourown.org/works/987654  ",
    ],
)
def test_parse_work_id(ref):
    assert parse_work_id(ref) == 987654


def test_parse_work_id_rejects_other_links():
    with pytest.raises(ValueError):
        parse_work_id("https://archiveofourown.org/users/someone")


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_fetch_asks_for_the_whole_work_without_the_adult_prompt():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, text="<html>work</html>")

    assert fetch_work(5, client=client(handler)) == "<html>work</html>"
    assert seen[0].path == "/works/5"
    assert seen[0].params["view_full_work"] == "true"
    assert seen[0].params["view_adult"] == "true"


def test_fetch_waits_and_retries_when_rate_limited():
    responses = iter(
        [httpx.Response(429, headers={"Retry-After": "12"}), httpx.Response(200, text="ok")]
    )
    waits = []

    assert fetch_work(5, client=client(lambda r: next(responses)), sleep=waits.append) == "ok"
    assert waits == [12]


def test_fetch_gives_up_after_retries():
    waits = []
    with pytest.raises(FetchError, match="limiting requests"):
        fetch_work(5, client=client(lambda r: httpx.Response(429)), retries=2, sleep=waits.append)
    assert waits == [60, 60]


def test_missing_work():
    with pytest.raises(FetchError, match="wasn't found"):
        fetch_work(5, client=client(lambda r: httpx.Response(404)))


def test_locked_work_explains_saving_the_page():
    def handler(request):
        if request.url.path == "/works/5":
            return httpx.Response(302, headers={"Location": "/users/login?restricted=true"})
        return httpx.Response(200, text="<html>Log in</html>")

    with pytest.raises(FetchError, match="logged-in AO3 users.*save the page"):
        fetch_work(5, client=client(handler))


def test_bot_protection_explains_saving_the_page():
    def handler(request):
        return httpx.Response(403, headers={"cf-ray": "abc"}, text="Just a moment...")

    with pytest.raises(FetchError, match="bot protection.*save the page"):
        fetch_work(5, client=client(handler))
