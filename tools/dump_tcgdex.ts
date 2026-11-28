/**
 * Dump a checkout of TCGdex's cards-database repository to JSONL, every language of a card in one object.
 *
 *     bun tools/dump_tcgdex.ts <cards-database checkout> <output directory>
 *
 * Writes series.jsonl, sets.jsonl, cards.jsonl and translations.json. It reuses the repository's own compiler
 * helpers, so a variant's variantId and a card's legality are the ones TCGdex's API serves. Unlike the API, it keeps
 * each variant's `languages`, and each card says which formats ban it by name (meta/legals.ts). translations.json is
 * the repository's meta/translations: the words the API puts in place of the English enum values, per language.
 * Adapted from pokemon_exploration/scripts/dump_tcgdex.ts.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const [repoArg, outArg] = process.argv.slice(2)
if (!repoArg || !outArg) throw new Error('usage: bun tools/dump_tcgdex.ts <cards-database checkout> <output directory>')
const REPO = path.resolve(repoArg)
const OUT = path.resolve(outArg)
const FOLDERS = ['data', 'data-asia']

const { variantToIdentifier } = await import(`${REPO}/server/compiler/utils/variantUtil`)
const { cardIsLegal } = await import(`${REPO}/server/compiler/utils/util`)
const legals: Record<string, { excludes: { cards: Array<string> } }> = await import(`${REPO}/meta/legals`)
// The formats that ban a card by its id, as the compiler reads them.
const FORMATS = ['standard', 'expanded']
const bannedIn = (id: string) => FORMATS.filter((f) => legals[f].excludes.cards.includes(id))

const jsonl = (rows: Array<unknown>) => rows.map((r) => JSON.stringify(r)).join('\n') + '\n'
const load = async (file: string) => (await import(file)).default
const files = (pattern: string, cwd: string) => Array.from(new Bun.Glob(pattern).scanSync({ cwd, absolute: true })).sort()

// Which images exist, per language, serie, set and card: the same file the compiler uses for `image`.
const assets: Record<string, any> = await (await fetch('https://assets.tcgdex.net/datas.json')).json()

const series: Array<object> = []
const sets: Array<object> = []
const cards: Array<object> = []

for (const folder of FOLDERS) {
	const root = `${REPO}/${folder}`
	for (const file of files('*.ts', root)) {
		const serie = await load(file)
		series.push({ ...serie, folder, file: path.basename(file, '.ts') })
	}
	for (const file of files('*/*.ts', root)) {
		const set = await load(file)
		// The repository holds placeholders (serie id 'null', a set id copied from another file): the file name
		// tells them apart.
		// The compiler's rule for a set's pictures: a logo per language, and one symbol for all, where the asset exists.
		const logos = Object.fromEntries(Object.keys(set.name)
			.filter((lang) => assets[lang]?.[set.serie.id]?.[set.id]?.logo)
			.map((lang) => [lang, `https://assets.tcgdex.net/${lang}/${set.serie.id}/${set.id}/logo`]))
		const symbol = assets.univ?.[set.serie.id]?.[set.id]?.symbol
			? `https://assets.tcgdex.net/univ/${set.serie.id}/${set.id}/symbol` : undefined
		sets.push({ ...set, serie: set.serie.id, folder, file: path.basename(file, '.ts'),
			serieFile: path.basename(path.dirname(file)), logos, symbol })
	}
	for (const file of files('*/*/*.ts', root)) {
		const card = await load(file)
		const localId = path.basename(file, '.ts')
		const set = card.set
		// The compiler's rule: the set and the card must both have the language.
		const languages = Object.keys(card.name).filter((lang) => lang in set.name)
		const images = Object.fromEntries(languages
			.filter((lang) => assets[lang]?.[set.serie.id]?.[set.id]?.[localId])
			.map((lang) => [lang, `https://assets.tcgdex.net/${lang}/${set.serie.id}/${set.id}/${localId}`]))
		const id = `${set.id}-${localId}`
		const banned = bannedIn(id)
		cards.push({
			...card,
			id,
			localId,
			set: set.id,
			setFile: path.basename(path.dirname(file)),
			serie: set.serie.id,
			folder,
			languages,
			images,
			// Legacy boolean variants have no ids: the API serves "generated" for them.
			variants: Array.isArray(card.variants)
				? card.variants.map((v: any) => ({ ...v, variantId: variantToIdentifier(v) }))
				: card.variants,
			legacyVariants: !Array.isArray(card.variants),
			legal: {
				standard: cardIsLegal('standard', card, localId),
				expanded: cardIsLegal('expanded', card, localId),
			},
			...(banned.length ? { banned } : {}),
		})
	}
}

mkdirSync(OUT, { recursive: true })
writeFileSync(`${OUT}/series.jsonl`, jsonl(series))
writeFileSync(`${OUT}/sets.jsonl`, jsonl(sets))
writeFileSync(`${OUT}/cards.jsonl`, jsonl(cards))
const translations = Object.fromEntries(files('*.json', `${REPO}/meta/translations`)
	.filter((file) => path.basename(file) !== 'schema.json')
	.map((file) => {
		// The enum tables only: a file also holds `$schema` and `__comment__` notes.
		const table = Object.entries(JSON.parse(readFileSync(file, 'utf-8'))).filter(([, v]) => typeof v === 'object')
		return [path.basename(file, '.json'), Object.fromEntries(table)]
	}))
writeFileSync(`${OUT}/translations.json`, JSON.stringify(translations, null, '\t') + '\n')
console.log(`${series.length} series, ${sets.length} sets, ${cards.length} cards -> ${OUT}`)
