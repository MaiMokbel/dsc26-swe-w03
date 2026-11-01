"""RFC 9457 problem responses."""
from fastapi.responses import JSONResponse


### ProblemError: nersy beha ay error (401, 404, 409...) w el handler yet7awel-ha le problem+json
class ProblemError(Exception):
    def __init__(self, status: int, title: str, detail: str | None = None,
                 headers: dict[str, str] | None = None, extra: dict | None = None):
        self.status = status
        self.title = title
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra or {}


def problem_body(status: int, title: str, detail: str | None = None, extra: dict | None = None) -> dict:
    ### type, title, status lazem yekoono mawgoodeen (el assignment)
    body = {"type": f"https://rawajpay.example/problems/{status}", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    if extra:
        body.update(extra)
    return body


def problem_response(status: int, title: str, detail: str | None = None,
                     headers: dict[str, str] | None = None, extra: dict | None = None) -> JSONResponse:
    return JSONResponse(
        problem_body(status, title, detail, extra),
        status_code=status,
        headers=headers,
        media_type="application/problem+json",  ### el content-type el matlob
    )