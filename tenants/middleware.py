from django.db import connection
from django.http import HttpResponseBadRequest


class QueryStringGuardMiddleware:
    """
    Reject requests whose raw querystring is unreasonably long.
    This prevents bots / malformed links from generating huge responses
    when templates echo GET values into hundreds of links.
    """
    MAX_QS_LENGTH = 2048  # 2 KB is generous for real filter use

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        qs = request.META.get('QUERY_STRING', '')
        if len(qs) > self.MAX_QS_LENGTH:
            return HttpResponseBadRequest(
                'Query string too long. Please shorten your filters.',
                content_type='text/plain',
            )
        return self.get_response(request)


class TenantPublicSchemaMiddleware:
    """
    After TenantMainMiddleware sets the schema, this middleware
    appends 'public' to the search_path so shared apps (like cars)
    are visible from all tenant schemas.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(connection, "tenant", None)
        if tenant and tenant.schema_name != "public":
            cursor = connection.cursor()
            cursor.execute("SHOW search_path")
            current = cursor.fetchone()[0]
            if "public" not in current:
                cursor.execute(f"SET search_path TO {current}, public")
        return self.get_response(request)
