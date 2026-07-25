# Datový model

Křížovkář ukládá křížovky jako textové dokumenty v YAML 1.2. Model je nezávislý na budoucím editoru, aby stejné soubory mohly používat různé nástroje.

## Verze 1

První iterace popisuje pouze obdélníkový rozměr celé mřížky:

```yaml
format: krizovkar
version: 1
grid:
  width: 15
  height: 10
```

### Položky

- `format` musí mít hodnotu `krizovkar` a jednoznačně označuje formát souboru.
- `version` musí mít hodnotu `1` a označuje hlavní verzi datového modelu.
- `grid.width` je šířka mřížky v buňkách, tedy počet sloupců zleva doprava.
- `grid.height` je výška mřížky v buňkách, tedy počet řádků shora dolů.

Oba rozměry jsou povinná kladná celá čísla. Hodnota `15` proto znamená patnáct buněk, nikoli fyzickou délku nebo počet pixelů. Souřadnice ani obsah jednotlivých buněk tato iterace ještě nedefinuje.

## Validace

Strojová pravidla jsou v [JSON Schema pro verzi 1](../src/krizovkar/schemas/krizovkar-v1.schema.json). Schéma odmítá chybějící, neznámé a chybně napsané položky i nulové, záporné nebo neceločíselné rozměry.

Úplný minimální dokument je v [příkladu](../examples/minimal.yaml).

## Rozvoj formátu

- Nová data se mají přidávat pod srozumitelně pojmenované položky, nikoli odvozovat z pořadí zápisu v YAML.
- Zpětně kompatibilní rozšíření mohou zůstat ve verzi `1`; nekompatibilní změna vyžaduje novou hlavní verzi.
- Příklad, dokumentace a schéma se při změně modelu aktualizují společně.
