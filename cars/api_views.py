"""
Public JSON API for fetching car data.
External websites can call these endpoints to embed car info.

Usage:
  GET /api/car/<lot_number>/          → fetch by lot number
  GET /api/car/slug/<slug>/           → fetch by slug

Response includes CORS headers so any domain can call it.
"""
import json
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache

from .models import ApiCar


def _cors(response):
    """Add CORS headers to allow cross-domain requests."""
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def _car_to_dict(car, request=None):
    """Serialize a car to a JSON-safe dict."""
    images = car.images or []
    if isinstance(images, str):
        try:
            images = json.loads(images)
        except Exception:
            images = [images] if images else []

    # Build absolute URL to car detail page
    car_url = None
    if car.slug:
        if request:
            car_url = request.build_absolute_uri(f"/cars/{car.slug}/")
        else:
            car_url = f"/cars/{car.slug}/"

    return {
        "id": car.id,
        "slug": car.slug,
        "url": car_url,
        "lot_number": car.lot_number,
        "title": car.title,
        "year": car.year,
        "price": car.price,
        "mileage": car.mileage,
        "fuel": car.fuel,
        "transmission": car.transmission,
        "drive_wheel": car.drive_wheel,
        "condition": car.condition,
        "status": car.status,
        "address": car.address,
        "image": car.image,
        "images": images,
        "manufacturer": {
            "id": car.manufacturer_id,
            "name": car.manufacturer.name,
            "name_ar": car.manufacturer.name_ar,
            "logo": car.manufacturer.logo,
        } if car.manufacturer_id else None,
        "model": {
            "id": car.model_id,
            "name": car.model.name,
        } if car.model_id else None,
        "badge": {
            "id": car.badge_id,
            "name": car.badge.name,
        } if car.badge_id else None,
        "color": {
            "id": car.color_id,
            "name": car.color.name,
        } if car.color_id else None,
        "category": {
            "id": car.category_id,
            "name": car.category.name,
        } if car.category_id else None,
        "auction_date": car.auction_date.isoformat() if car.auction_date else None,
        "auction_name": car.auction_name,
        "vin": car.vin,
        "power": car.power,
        "seat_count": car.seat_count,
    }


@csrf_exempt
@require_GET
def api_car_by_lot(request, lot_number):
    """GET /api/car/<lot_number>/"""
    cache_key = f"api:car:lot:{lot_number}"
    data = cache.get(cache_key)

    if data is None:
        try:
            car = ApiCar.objects.select_related(
                'manufacturer', 'model', 'badge', 'color', 'category'
            ).get(lot_number=lot_number)
            data = _car_to_dict(car, request)
            cache.set(cache_key, data, 60 * 60)  # cache 1 hour
        except ApiCar.DoesNotExist:
            return _cors(JsonResponse({"error": "Car not found"}, status=404))

    return _cors(JsonResponse(data))


@csrf_exempt
@require_GET
def api_car_by_slug(request, slug):
    """GET /api/car/slug/<slug>/"""
    cache_key = f"api:car:slug:{slug}"
    data = cache.get(cache_key)

    if data is None:
        try:
            car = ApiCar.objects.select_related(
                'manufacturer', 'model', 'badge', 'color', 'category'
            ).get(slug=slug)
            data = _car_to_dict(car, request)
            cache.set(cache_key, data, 60 * 60)  # cache 1 hour
        except ApiCar.DoesNotExist:
            return _cors(JsonResponse({"error": "Car not found"}, status=404))

    return _cors(JsonResponse(data))
