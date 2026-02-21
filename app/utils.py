'''Utility helper functions for the AutoSocial project.'''
from __future__ import annotations

def normalize_image_url(u: str | None) -> str | None:
    '''
    Normalize known duplicated path segments in image URLs coming from R2 uploads.

    Examples:
    - replace '/ig/post/ig/post/' -> '/ig/post/'
    - replace '/ig/story/ig/story/' -> '/ig/story/'
    '''
    if not u:
        return u
    return u.replace('/ig/post/ig/post/', '/ig/post/').replace('/ig/story/ig/story/', '/ig/story/')

