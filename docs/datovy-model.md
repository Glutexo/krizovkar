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

Oba rozměry jsou povinná kladná celá čísla. Hodnota `15` proto znamená patnáct buněk, nikoli fyzickou délku nebo počet pixelů.

## Buňka písmene

Volitelná položka `grid.cells` obsahuje matici buněk. Vnější seznam představuje řádky shora dolů a každý vnitřní seznam buňky zleva doprava:

```yaml
grid:
  width: 2
  height: 2
  cells:
    - [{type: letter, value: A}, {type: letter, value: H}]
    - [{type: letter, value: O}, {type: letter, value: J}]
```

Pokud je `cells` uvedené, musí obsahovat přesně `grid.height` řádků a každý řádek přesně `grid.width` buněk. Jeho vynechání znamená prázdnou mřížku bez určených buněk.

Prvním podporovaným typem je písmeno:

- `type` musí mít hodnotu `letter`,
- `value` musí být právě jedno velké písmeno anglické abecedy od `A` do `Z`.

Pozice v matici jednoznačně určuje souřadnici buňky; samostatné souřadnice se proto do každé buňky neopakují. Další typy buněk tato iterace ještě nedefinuje.

## Validace

Strojová pravidla jsou v [JSON Schema pro verzi 1](../src/krizovkar/schemas/krizovkar-v1.schema.json). Schéma odmítá chybějící, neznámé a chybně napsané položky i nulové, záporné nebo neceločíselné rozměry.

Úplný minimální dokument je v [příkladu](../examples/minimal.yaml).

Vyplněný dokument je v [příkladu s náhodnými písmeny](../examples/random-letters.yaml).

## Rozvoj formátu

- Nová data se mají přidávat pod srozumitelně pojmenované položky, nikoli odvozovat z pořadí zápisu v YAML.
- Zpětně kompatibilní rozšíření mohou zůstat ve verzi `1`; nekompatibilní změna vyžaduje novou hlavní verzi.
- Příklad, dokumentace a schéma se při změně modelu aktualizují společně.
