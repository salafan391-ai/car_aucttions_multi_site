# Posts Tenant Isolation

## Overview
Posts are now fully isolated per tenant, just like `SiteCar` models. Each tenant site has its own separate collection of posts that cannot be accessed by other tenants.

## What Changed

### 1. Models (No Changes Needed)
The `Post` model already had a `tenant` ForeignKey field, so no model changes were required:
```python
tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, null=True, blank=True, verbose_name="الموقع")
```

### 2. Views Updated (`cars/views.py`)

Added helper functions:
- `_is_public_schema()` - Check if in public schema
- `_get_current_tenant()` - Get current tenant from connection

Updated all post views to filter by tenant:

#### `post_list`
- Filters published posts by current tenant
- Shows only posts belonging to the current tenant site

#### `post_detail`
- Filters post by ID AND tenant
- Prevents cross-tenant access to posts

#### `post_like_toggle`
- Checks tenant ownership before allowing likes
- Users can only like posts from their current tenant site

#### `post_comment_add`
- Verifies tenant ownership before adding comments
- Comments are only allowed on posts from the current tenant

#### `post_comment_delete`
- Maintains tenant isolation for comment deletion

#### `post_create`
- **Auto-sets `tenant` field** when creating new posts
- New posts are automatically assigned to the current tenant

#### `post_edit`
- Filters by tenant to ensure users can only edit posts from their tenant
- Prevents cross-tenant post editing

#### `post_image_delete`
- Checks tenant through the post relationship
- Prevents deletion of images from other tenants' posts

#### `home`
- Updated to filter post counts and latest post by tenant
- Each tenant sees their own post statistics

### 3. Admin Interface Updated (`cars/admin.py`)

#### `PostAdmin`
- Added `tenant` to list_display and list_filter
- Added `tenant` field to form fieldsets
- **`get_queryset()`** - Filters admin list to show only current tenant's posts
- **`save_model()`** - Auto-sets tenant when creating new posts in admin

#### `PostImageAdmin`
- Filters images by tenant through post relationship

#### `PostLikeAdmin`
- Filters likes by tenant through post relationship

#### `PostCommentAdmin`
- Filters comments by tenant through post relationship

## How It Works

### Tenant Detection
```python
from django.db import connection

tenant = getattr(connection, 'tenant', None)
schema_name = connection.schema_name
```

### Public Schema Check
```python
if connection.schema_name == 'public':
    # Public schema - show all posts or redirect
else:
    # Tenant schema - filter by tenant
```

### Automatic Tenant Assignment
When creating a post:
```python
post = Post.objects.create(
    title=title,
    content=content,
    author=request.user,
    tenant=tenant,  # ← Automatically set
    # ...
)
```

### Tenant Filtering
When querying posts:
```python
# Get posts for current tenant only
posts = Post.objects.filter(is_published=True)
if tenant and not _is_public_schema():
    posts = posts.filter(tenant=tenant)
```

## Benefits

1. **Data Isolation**: Each tenant can only see and manage their own posts
2. **Security**: Cross-tenant access is prevented at the view and admin level
3. **Automatic**: Tenant assignment happens automatically on post creation
4. **Consistent**: Uses the same pattern as `SiteCar` for consistency
5. **Admin Support**: Django admin interface respects tenant boundaries

## Testing

To verify tenant isolation:

1. **Create posts on different tenant sites**:
   - Go to tenant1.yourdomain.com and create a post
   - Go to tenant2.yourdomain.com and create another post

2. **Verify isolation**:
   - Each tenant should only see their own posts
   - Post IDs won't conflict (different databases)
   - Editing URLs work only within the same tenant

3. **Test admin interface**:
   - Login to admin on tenant1 - should only see tenant1 posts
   - Login to admin on tenant2 - should only see tenant2 posts

4. **Test cross-tenant access** (should fail):
   - Try accessing tenant1 post from tenant2 URL
   - Should get 404 error

## Related Models

All related models also respect tenant isolation:
- `PostImage` - Filtered through post's tenant
- `PostLike` - Filtered through post's tenant  
- `PostComment` - Filtered through post's tenant

## Migration Notes

**No database migration required!** The `tenant` field already exists in the database. This was purely a code change to:
- Add tenant filtering to queries
- Auto-set tenant on creation
- Update admin interface

If you have existing posts without a tenant assigned, you may want to run a data migration to assign them to appropriate tenants.
