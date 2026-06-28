from django.db import migrations


# IMMUTABLE function that normalises both damage sources into type tags:
#   - auction `markers`  {panel: {status, code}}
#   - encar  `extra_features.outers/inners[*].statusTypes[*].code`
# 'replaced' = auction status=replaced OR encar code 'X' (교환/exchange)
# 'painted'  = either source has a code containing 'W' (판금·용접/bodywork)
# A GIN index on the expression makes `&& ARRAY[...]` lookups fast.
FUNC = r"""
CREATE OR REPLACE FUNCTION car_dmg_types(ef jsonb, mk jsonb)
RETURNS text[] LANGUAGE sql IMMUTABLE AS $func$
  SELECT ARRAY(SELECT DISTINCT t FROM (
    SELECT 'replaced' AS t FROM jsonb_each(CASE WHEN jsonb_typeof(mk)='object' THEN mk ELSE '{}'::jsonb END) e WHERE e.value->>'status'='replaced'
    UNION ALL
    SELECT 'painted' FROM jsonb_each(CASE WHEN jsonb_typeof(mk)='object' THEN mk ELSE '{}'::jsonb END) e WHERE upper(e.value->>'code') LIKE '%W%'
    UNION ALL
    SELECT 'replaced' FROM jsonb_array_elements(
        (CASE WHEN jsonb_typeof(ef->'outers')='array' THEN ef->'outers' ELSE '[]'::jsonb END) ||
        (CASE WHEN jsonb_typeof(ef->'inners')='array' THEN ef->'inners' ELSE '[]'::jsonb END)) p,
        jsonb_array_elements(CASE WHEN jsonb_typeof(p->'statusTypes')='array' THEN p->'statusTypes' ELSE '[]'::jsonb END) s
      WHERE s->>'code'='X'
    UNION ALL
    SELECT 'painted' FROM jsonb_array_elements(
        (CASE WHEN jsonb_typeof(ef->'outers')='array' THEN ef->'outers' ELSE '[]'::jsonb END) ||
        (CASE WHEN jsonb_typeof(ef->'inners')='array' THEN ef->'inners' ELSE '[]'::jsonb END)) p,
        jsonb_array_elements(CASE WHEN jsonb_typeof(p->'statusTypes')='array' THEN p->'statusTypes' ELSE '[]'::jsonb END) s
      WHERE upper(s->>'code') LIKE '%W%'
  ) x);
$func$;
"""

INDEX = ("CREATE INDEX IF NOT EXISTS cars_apicar_dmg_types_gin "
         "ON cars_apicar USING gin (car_dmg_types(extra_features, markers));")


class Migration(migrations.Migration):

    dependencies = [("cars", "0032_apicar_markers")]

    operations = [
        migrations.RunSQL(FUNC, reverse_sql="DROP FUNCTION IF EXISTS car_dmg_types(jsonb, jsonb);"),
        migrations.RunSQL(INDEX, reverse_sql="DROP INDEX IF EXISTS cars_apicar_dmg_types_gin;"),
    ]
