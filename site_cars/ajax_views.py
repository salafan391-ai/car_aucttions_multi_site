"""
AJAX Image Upload View (Optional - For Real-Time Progress)

This view can be used for AJAX uploads with real progress tracking.
Currently not integrated but available for future enhancement.
"""
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from .models import SiteCar, SiteCarImage
from .image_utils import optimize_image


@staff_member_required
@require_POST
def ajax_upload_images(request, car_id):
    """
    AJAX endpoint for uploading images with real-time progress
    
    Usage (JavaScript):
    ```javascript
    const formData = new FormData();
    formData.append('image', fileInput.files[0]);
    
    fetch('/ajax-upload-images/' + carId + '/', {
        method: 'POST',
        body: formData,
        headers: {
            'X-CSRFToken': getCookie('csrftoken')
        }
    })
    .then(response => response.json())
    .then(data => {
        console.log('Uploaded:', data.url);
    });
    ```
    """
    try:
        car = SiteCar.objects.get(pk=car_id)
        uploaded_images = []
        
        files = request.FILES.getlist('images')
        
        for idx, file in enumerate(files):
            # Optimize image
            optimized = optimize_image(file)
            
            # Create image record
            img = SiteCarImage.objects.create(
                car=car,
                image=optimized,
                order=car.gallery.count() + idx
            )
            
            uploaded_images.append({
                'id': img.id,
                'url': img.image.url,
                'order': img.order
            })
        
        return JsonResponse({
            'success': True,
            'images': uploaded_images,
            'count': len(uploaded_images)
        })
    
    except SiteCar.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'السيارة غير موجودة'
        }, status=404)
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# To use this view, add to urls.py:
# path('ajax-upload-images/<int:car_id>/', views.ajax_upload_images, name='ajax_upload_images'),
