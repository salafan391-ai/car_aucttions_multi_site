from whitenoise.storage import CompressedManifestStaticFilesStorage


class RelaxedManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """
    Same as CompressedManifestStaticFilesStorage but does NOT raise ValueError
    when a static file is missing from the manifest. Returns the original path
    instead, so a missing file causes a 404 rather than a 500.
    """
    manifest_strict = False
