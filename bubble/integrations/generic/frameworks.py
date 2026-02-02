"""Built-in framework configurations.

These configurations should produce identical results to the framework-specific
detectors in flow/integrations/flask/, fastapi/, and django/.
"""

from bubble.integrations.generic.config import (
    ClassRoutePattern,
    DecoratorRoutePattern,
    FrameworkConfig,
    HandlerPattern,
)

FLASK_CONFIG = FrameworkConfig(
    name="flask",
    route_patterns=[
        DecoratorRoutePattern(
            decorator_pattern="route",
            path_source="arg[0]",
            method_source="kwarg[methods]",
            default_method="GET",
        ),
        DecoratorRoutePattern(
            decorator_pattern="expose",
            path_source="arg[0]",
            method_source="kwarg[methods]",
            default_method="GET",
        ),
    ],
    handler_patterns=[
        HandlerPattern(decorator_pattern="errorhandler"),
    ],
    handled_exceptions=[
        "werkzeug.exceptions.HTTPException",
    ],
)


FASTAPI_CONFIG = FrameworkConfig(
    name="fastapi",
    route_patterns=[
        DecoratorRoutePattern(
            decorator_pattern="get",
            path_source="arg[0]",
            method_source="decorator_name",
        ),
        DecoratorRoutePattern(
            decorator_pattern="post",
            path_source="arg[0]",
            method_source="decorator_name",
        ),
        DecoratorRoutePattern(
            decorator_pattern="put",
            path_source="arg[0]",
            method_source="decorator_name",
        ),
        DecoratorRoutePattern(
            decorator_pattern="delete",
            path_source="arg[0]",
            method_source="decorator_name",
        ),
        DecoratorRoutePattern(
            decorator_pattern="patch",
            path_source="arg[0]",
            method_source="decorator_name",
        ),
        DecoratorRoutePattern(
            decorator_pattern="options",
            path_source="arg[0]",
            method_source="decorator_name",
        ),
        DecoratorRoutePattern(
            decorator_pattern="head",
            path_source="arg[0]",
            method_source="decorator_name",
        ),
    ],
    handler_patterns=[
        HandlerPattern(decorator_pattern="exception_handler"),
        HandlerPattern(call_pattern="*.add_exception_handler"),
    ],
    handled_exceptions=[
        "fastapi.HTTPException",
        "starlette.exceptions.HTTPException",
    ],
)


DJANGO_CONFIG = FrameworkConfig(
    name="django",
    route_patterns=[
        DecoratorRoutePattern(
            decorator_pattern="api_view",
            path_source="arg[0]",
            method_source="arg[0]",
            default_method="GET",
        ),
    ],
    class_patterns=[
        ClassRoutePattern(
            base_classes=[
                "APIView",
                "ViewSet",
                "ModelViewSet",
                "ReadOnlyModelViewSet",
                "GenericAPIView",
                "GenericViewSet",
                "ListAPIView",
                "CreateAPIView",
                "RetrieveAPIView",
                "UpdateAPIView",
                "DestroyAPIView",
                "ListCreateAPIView",
                "RetrieveUpdateAPIView",
                "RetrieveDestroyAPIView",
                "RetrieveUpdateDestroyAPIView",
                "View",
                "TemplateView",
                "RedirectView",
                "FormView",
                "DetailView",
                "ListView",
            ],
        ),
    ],
    handler_patterns=[
        HandlerPattern(decorator_pattern="exception_handler"),
        HandlerPattern(decorator_pattern="api_exception_handler"),
    ],
    handled_exceptions=[
        "rest_framework.exceptions.APIException",
    ],
)


FRAMEWORK_CONFIGS: dict[str, FrameworkConfig] = {
    "flask": FLASK_CONFIG,
    "fastapi": FASTAPI_CONFIG,
    "django": DJANGO_CONFIG,
}


def get_framework_config(name: str) -> FrameworkConfig | None:
    """Get a built-in framework configuration by name."""
    return FRAMEWORK_CONFIGS.get(name.lower())
