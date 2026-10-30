from fastapi import HTTPException, status


def not_found(what: str = "Not found") -> HTTPException:
    # Also used for other organizations' records, so their existence is never revealed.
    return HTTPException(status.HTTP_404_NOT_FOUND, what)


def forbidden(what: str = "Forbidden") -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, what)


def conflict(what: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, what)


def bad_request(what: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, what)


def unprocessable(what: str | dict | list) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, what)
