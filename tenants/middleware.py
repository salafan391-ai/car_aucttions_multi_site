from django.db import connection


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
