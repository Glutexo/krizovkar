# Datový model

Křížovkář ukládá data jako textové dokumenty v YAML 1.2. Model je nezávislý na budoucím editoru, aby stejné soubory mohly používat různé nástroje.

Existují dva samostatné druhy dokumentů:

- zadání `specification` popisuje, co se má do křížovky vložit,
- cílová mřížka `grid` popisuje konkrétní výsledek po rozložení.

```text
specification → generování a rozložení → grid → vykreslení PDF
```

Každý druh má vlastní JSON Schema a vlastní Pythonový loader. Dokument proto vždy obsahuje povinnou položku `kind`; nástroj nemusí jeho význam odhadovat z ostatních položek.

## Cílová mřížka, verze 1

Cílová mřížka popisuje obdélníkový rozměr a případný obsah buněk:

```yaml
format: krizovkar
kind: grid
version: 1
grid:
  width: 15
  height: 10
```

### Položky

- `format` musí mít hodnotu `krizovkar` a jednoznačně označuje formát souboru.
- `kind` musí mít hodnotu `grid`.
- `version` musí mít hodnotu `1` a označuje hlavní verzi modelu cílové mřížky.
- `grid.width` je šířka mřížky v buňkách, tedy počet sloupců zleva doprava.
- `grid.height` je výška mřížky v buňkách, tedy počet řádků shora dolů.

Oba rozměry jsou povinná kladná celá čísla. Hodnota `15` proto znamená patnáct buněk, nikoli fyzickou délku nebo počet pixelů.

## Buňky s písmeny

Volitelná položka `grid.cells` obsahuje matici buněk. Vnější seznam představuje řádky shora dolů a každý vnitřní seznam buňky zleva doprava:

```yaml
grid:
  width: 2
  height: 2
  cells:
    - [{type: letter, value: A}, {type: secret, value: H}]
    - [{type: letter, value: O}, {type: secret, value: J}]
```

Pokud je `cells` uvedené, musí obsahovat přesně `grid.height` řádků a každý řádek přesně `grid.width` buněk. Jeho vynechání znamená prázdnou mřížku bez určených buněk.

Podporované typy jsou:

- `type: letter` pro běžnou písmennou buňku,
- `type: secret` pro zvýrazněnou buňku, jejíž písmeno patří do tajenky.

U obou typů musí být `value` právě jedno velké písmeno anglické abecedy od `A` do `Z`. Renderer odlišuje tajenkovou buňku světle šedým pozadím.

Pozice v matici jednoznačně určuje souřadnici buňky; samostatné souřadnice se proto do každé buňky neopakují. Cílová mřížka pouze označuje buňky tajenky. Její pořadí, seskupení a význam budou součástí zadání `specification`.

## Zadání, verze 1

Zadání je zdrojový dokument, ze kterého budoucí generátor vytvoří cílovou mřížku:

```yaml
format: krizovkar
kind: specification
version: 1
```

Tato první iterace definuje pouze samostatnou obálku dokumentu. Struktura slov, nápověd, tajenek a pravidel skládání bude doplněna následně, aby nebyla omylem svázána s interní podobou výsledné mřížky.

## Validace

Strojová pravidla jsou v samostatných schématech pro [cílovou mřížku](../src/krizovkar/schemas/grid-v1.schema.json) a [zadání](../src/krizovkar/schemas/specification-v1.schema.json). Schéma mřížky odmítá chybějící, neznámé a chybně napsané položky i nulové, záporné nebo neceločíselné rozměry.

Minimální dokumenty jsou v příkladech [cílové mřížky](../examples/grid-minimal.yaml) a [zadání](../examples/specification-minimal.yaml).

Vyplněná cílová mřížka je v [příkladu s náhodnými písmeny](../examples/grid-random-letters.yaml).

Smíšené typy buněk ukazuje [příklad s tajenkou](../examples/grid-secret.yaml).

## Rozvoj formátu

- Nová data se mají přidávat pod srozumitelně pojmenované položky, nikoli odvozovat z pořadí zápisu v YAML.
- Zpětně kompatibilní rozšíření mohou zůstat ve verzi `1`; nekompatibilní změna vyžaduje novou hlavní verzi.
- Příklady, dokumentace a příslušné schéma se při změně modelu aktualizují společně.
