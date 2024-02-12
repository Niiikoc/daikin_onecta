from homeassistant.core import HomeAssistant
from homeassistant.components.application_credentials import AuthorizationServer


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return authorization server."""
    return AuthorizationServer(
        authorize_url="https://idp.onecta.daikineurope.com/v1/oidc/authorize",
        token_url="https://idp.onecta.daikineurope.com/v1/oidc/token"
    )
