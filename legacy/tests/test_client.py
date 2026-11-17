import json

import pytest
import requests

from auth import AuthError, mask_secrets, parse_app_data, register_secret
from client import ExportStatus, extract_new_id, parse_exports_table


def body(app: dict, extra: str = "") -> str:
    return f"<html><body data-app-data='{json.dumps(app)}'>{extra}</body></html>"


def test_parse_app_data_ok():
    app = parse_app_data(body({"csrf-token": "tok123456", "userId": 42}))
    assert app.user_id == 42 and app.csrf_token == "tok123456"
    assert "tok123456" not in mask_secrets("x tok123456 y")


@pytest.mark.parametrize("html", [
    body({"csrf-token": "t", "userId": 0}),
    body({"csrf-token": "t"}),
    body({"csrf-token": "t", "userId": 5}, '<form action="/account/login"><input type="password"></form>'),
    "<html><body></body></html>",
])
def test_parse_app_data_guest(html):
    with pytest.raises(AuthError, match="cookie устарели"):
        parse_app_data(html)


def test_mask_cookie_header():
    register_secret("supersecretvalue")
    s = mask_secrets("Cookie: golden_key=abc; PHPSESSID=def\nfoo supersecretvalue")
    assert "abc" not in s and "def" not in s and "supersecretvalue" not in s


TABLE = """
<table class="js-exports-table"><tbody>
<tr data-export-id="11"><td>01.01</td><td>Продажи</td><td>период</td><td>Готовится</td></tr>
<tr data-export-id="12"><td>01.01</td><td>Продажи</td><td>период</td>
  <td><a class="js-export-download" href="/exports/download/12">Скачать</a></td></tr>
<tr data-export-id="13"><td>01.01</td><td>Продажи</td><td>период</td><td>Файл удалён</td></tr>
</tbody></table>"""


def test_parse_exports_table():
    rows = parse_exports_table(TABLE, "https://funpay.com/exports/")
    assert rows["11"].status is ExportStatus.PENDING
    assert rows["12"].status is ExportStatus.READY
    assert rows["12"].download_url == "https://funpay.com/exports/download/12"
    assert rows["13"].status is ExportStatus.DELETED


def make_resp(url: str, headers: dict | None = None, content: bytes = b"") -> requests.Response:
    r = requests.Response()
    r.url, r.status_code, r._content = url, 200, content
    r.headers.update(headers or {})
    return r


def test_extract_new_id_from_redirect():
    first = make_resp("https://funpay.com/exports/create", {"Location": "/exports/?new=777"})
    final = make_resp("https://funpay.com/exports/?new=777")
    final.history = [first]
    assert extract_new_id(final) == "777"


def test_extract_new_id_from_json():
    r = make_resp("https://funpay.com/exports/create", {"Content-Type": "application/json"},
                  json.dumps({"url": "/exports/?new=55"}).encode())
    assert extract_new_id(r) == "55"
    assert extract_new_id(make_resp("https://funpay.com/exports/create")) is None


def test_unpack_zip(tmp_path):
    import zipfile
    from client import unpack_zip
    arc = tmp_path / "a.zip"
    with zipfile.ZipFile(arc, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("funpay_sales_x.jsonl", '{"a": 1}\n{"a": 2}')
        zf.writestr("readme.txt", "ignored")
    dest = tmp_path / "out.jsonl"
    unpack_zip(arc, dest)
    assert dest.read_text(encoding="utf-8") == '{"a": 1}\n{"a": 2}\n'


def test_unpack_empty_zip_member(tmp_path):
    import zipfile
    from client import unpack_zip
    arc = tmp_path / "a.zip"
    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("funpay_sales_x.jsonl", "")
    dest = tmp_path / "out.jsonl"
    unpack_zip(arc, dest)
    assert dest.read_bytes() == b""
