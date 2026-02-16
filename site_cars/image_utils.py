"""
Image optimization utilities for handling bulk image uploads efficiently
"""
from PIL import Image
from io import BytesIO
from django.core.files.uploadedfile import InMemoryUploadedFile
import sys


def optimize_image(image_field, max_width=1920, max_height=1080, quality=85):
    """
    Optimize an uploaded image by:
    1. Resizing to max dimensions while maintaining aspect ratio
    2. Compressing with specified quality
    3. Converting to RGB if needed
    
    Args:
        image_field: Django UploadedFile object
        max_width: Maximum width in pixels
        max_height: Maximum height in pixels
        quality: JPEG quality (1-100)
    
    Returns:
        InMemoryUploadedFile: Optimized image
    """
    try:
        # Open the image
        img = Image.open(image_field)
        
        # Convert RGBA to RGB if needed (for JPEG)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        # Resize if needed
        if img.width > max_width or img.height > max_height:
            img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        
        # Save to BytesIO
        output = BytesIO()
        img_format = 'JPEG'
        img.save(output, format=img_format, quality=quality, optimize=True)
        output.seek(0)
        
        # Create InMemoryUploadedFile
        return InMemoryUploadedFile(
            output,
            'ImageField',
            f"{image_field.name.split('.')[0]}.jpg",
            'image/jpeg',
            sys.getsizeof(output),
            None
        )
    except Exception as e:
        # If optimization fails, return original
        print(f"Image optimization failed: {e}")
        return image_field


def optimize_thumbnail(image_field, max_width=400, max_height=300, quality=80):
    """
    Create an optimized thumbnail version of an image
    
    Args:
        image_field: Django UploadedFile object
        max_width: Maximum width in pixels
        max_height: Maximum height in pixels
        quality: JPEG quality (1-100)
    
    Returns:
        InMemoryUploadedFile: Optimized thumbnail
    """
    return optimize_image(image_field, max_width, max_height, quality)


def batch_optimize_images(image_list, max_workers=3):
    """
    Optimize multiple images in parallel (limited workers to prevent memory issues)
    
    Args:
        image_list: List of uploaded image files
        max_workers: Maximum number of parallel workers (keep low for Heroku)
    
    Returns:
        List of optimized images
    """
    from concurrent.futures import ThreadPoolExecutor
    
    # Limit to prevent memory issues on Heroku
    optimized = []
    
    # Process in batches to avoid memory spikes
    batch_size = max_workers
    for i in range(0, len(image_list), batch_size):
        batch = image_list[i:i+batch_size]
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(optimize_image, img) for img in batch]
            for future in futures:
                optimized.append(future.result())
    
    return optimized
