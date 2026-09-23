/** Shared DOM component. React can mount it through a ref; WordPress can use it directly. */
export function gameAsset(metadata, base, { sizes = '100vw', priority = false } = {}) {
  if (metadata.version !== 1 || !Array.isArray(metadata.variants) || !metadata.variants.length)
    throw new Error('Expected asset-prepare metadata v1');
  if (!metadata.decorative && !metadata.alt?.trim()) throw new Error('Meaningful assets require alt text');
  const url = new URL(base, document.baseURI);
  if (!['http:', 'https:'].includes(url.protocol) || url.origin !== location.origin)
    throw new Error('Serve prepared assets from the same origin');
  const variants = metadata.variants.map(variant => {
    if (!/^[\w-]+\.(avif|webp)$/.test(variant.file) || !['avif', 'webp'].includes(variant.format) ||
        !Number.isInteger(variant.width) || !Number.isInteger(variant.height) || variant.width < 1 || variant.height < 1)
      throw new Error('Invalid prepared asset variant');
    return { ...variant, url: new URL(variant.file, url.href.replace(/\/?$/, '/')).href };
  });
  const picture = document.createElement('picture');
  picture.className = 'mc-game-asset';
  picture.dataset.preset = metadata.preset;
  if (metadata.decorative) picture.setAttribute('aria-hidden', 'true');
  for (const format of ['avif', 'webp']) {
    const group = variants.filter(item => item.format === format).sort((a, b) => a.width - b.width);
    if (!group.length) throw new Error(`Missing ${format} variants`);
    const source = document.createElement('source');
    source.type = `image/${format}`;
    source.srcset = group.map(item => `${item.url} ${item.width}w`).join(', ');
    source.sizes = sizes;
    picture.append(source);
  }
  const fallback = variants.filter(item => item.format === 'webp').sort((a, b) => b.width - a.width)[0];
  const img = document.createElement('img');
  img.src = fallback.url;
  img.alt = metadata.decorative ? '' : metadata.alt;
  img.width = fallback.width;
  img.height = fallback.height;
  img.loading = priority ? 'eager' : 'lazy';
  img.fetchPriority = priority ? 'high' : 'auto';
  img.decoding = 'async';
  const focal = metadata.focal_point;
  if (!Array.isArray(focal) || focal.length !== 2 || focal.some(n => !Number.isFinite(n) || n < 0 || n > 1))
    throw new Error('Invalid focal point');
  img.style.objectPosition = focal.map(n => `${n * 100}%`).join(' ');
  const overlay = metadata.presentation?.overlay ?? 0;
  if (!Number.isFinite(overlay) || overlay < 0 || overlay > 1) throw new Error('Invalid overlay');
  picture.style.setProperty('--mc-asset-overlay', overlay);
  picture.append(img);
  return picture;
}
