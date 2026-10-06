# Paperless-ngx variant-hunt source table (2026-10-06)

One row per fixed authorization/permission check. Provenance is the
commit, not recollection. All commits read from the public
paperless-ngx repository; code references are to `src/documents/` at
v3.3.0 unless noted.

| # | Advisory | Class | Fixed in | Fix commit | Patch (file) | Added check (one line) |
|---|---|---|---|---|---|---|
| F1 | GHSA-386h-chg4-cfw9 | Share-link creation w/o doc auth | 2026-02-28 | `b010f65ae` | `serialisers.py` ShareLinkSerializer | `validate_document`: creator must have `view_document` on the document via `has_perms_owner_aware`, else 403 |
| F2 | GHSA-96jx-fj7m-qh6x | GlobalSearch IDOR (mail) | 2026-03-21 | `9e9fc6213` | `views.py` GlobalSearchView | mail rules/accounts scoped by `get_objects_for_user_owner_aware` instead of unfiltered queryset |
| F3 | GHSA-59xh-5vwx-4c4q | Superuser via UserViewSet | 2026-03-16 | `06b2d5102` | `src/paperless/views.py` UserViewSet | only superusers may set `is_superuser`/`is_staff` (bool-parsing fix included) |
| F4 | GHSA-x395-6h48-wr8v | storage_paths/test IDOR + Jinja sandbox | 2026-02-16 | `afaf39e43` | `views.py` + templating | test-form document field queryset scoped per-user; template context reduced to a safe subset |
| F5 | GHSA-7qqc-wrcw-2fj9 | Mail-account user-key bypass | 2026-02-22 | `65ca78e9e` | `paperless_mail/views.py` | update path verifies the account belongs to the requester (403 otherwise) |
| F6 | (beta hardening) | Versions endpoint missing global check | 2026-07-21 | `8aab34ea7` | `views.py` versions branch | global `change_document` ANDed with object check (was object-only) |
| F7 | (beta hardening) | Bulk op check overwrite | 2026-07-21 | `8aab34ea7` | `views.py` DocumentOperationPermissionMixin | `has_perms = has_perms and owner_check` (was overwrite); edit_pdf/remove_password delete_original gated on delete perm |
| F8 | (beta hardening) | Bulk mail delete partial batch | 2026-07-21 | `c28c532be` | mail bulk delete | whole-batch permission check up front; mixed batch rejected atomically |
| F9 | (beta hardening) | Autocomplete w/o doc perms | 2026-07-22 | `81795bc93` | `views.py` SearchAutoCompleteView | `permission_classes` gained `ViewDocumentsPermissions` (was bare `IsAuthenticated`) |

Non-server change noted and excluded: `e1aa9997d` (sharelink bundle
display labels, frontend only).

Checked-currently-covered at 3.3.0 (no hypothesis): ShareLinkBundle.create
(per-document `permitted_document_ids` check), notes GET/POST/DELETE
(view/change on parent doc), ShareLinkViewSet (`PaperlessObjectPermissions`),
bulk mixin AND-composition, GlobalSearch branches for object-permission
models (documents/tags/correspondents/types/paths/mail). Users, groups,
workflows and custom fields carry no per-object permissions in
`models.py`, so their unfiltered GlobalSearch branches under a global-perm
gate are by design.
