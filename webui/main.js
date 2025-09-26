import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'https://esm.sh/react@18';
import { createRoot } from 'https://esm.sh/react-dom@18/client';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(React.createElement);

const LIST_ORDER = ['artist', 'album', 'track'];
const initialState = window.__LIST_UI_STATE__ || {};

const ensureLists = (lists = {}) => ({
  artist: Array.isArray(lists.artist) ? lists.artist : [],
  album: Array.isArray(lists.album) ? lists.album : [],
  track: Array.isArray(lists.track) ? lists.track : [],
});

const withBannerIds = (banners = []) =>
  banners
    .filter((banner) => banner && banner.message)
    .map((banner, index) => ({
      id:
        typeof crypto !== 'undefined' && crypto.randomUUID
          ? crypto.randomUUID()
          : `${Date.now()}-${index}-${Math.random().toString(16).slice(2)}`,
      message: banner.message,
      isError: Boolean(banner.isError),
    }));

const normalizeIdentifier = (value) => {
  if (value === undefined || value === null) {
    return '';
  }
  const normalized = String(value).trim();
  if (!normalized) {
    return '';
  }
  if (
    normalized.startsWith('.') ||
    normalized.includes('/') ||
    normalized.includes('\\') ||
    normalized.includes('..')
  ) {
    return '';
  }
  return normalized;
};

const buildArtistPhotoUrl = (artistId) => {
  const normalized = normalizeIdentifier(artistId);
  return normalized ? `/photos/${encodeURIComponent(normalized)}` : '';
};

const buildAlbumPhotoUrl = (albumId) => {
  const normalized = normalizeIdentifier(albumId);
  if (!normalized) {
    return '';
  }
  const albumKey = normalizeIdentifier(`album_${normalized}`);
  return albumKey ? `/photos/${encodeURIComponent(albumKey)}` : '';
};

const SEARCH_CONFIG = {
  artist: {
    heading: 'Add artists from Qobuz',
    tagline: 'Queue full artist discographies by searching Qobuz.',
    idleMessage: 'Use the search to add artists by Qobuz ID.',
    endpoint: '/api/artist-search',
    selectEndpoint: '/api/artist-select',
    fields: [
      {
        key: 'artist',
        label: 'Artist',
        placeholder: 'Search Qobuz artists',
        type: 'search',
        required: true,
      },
    ],
    buildQuery: (inputs) => inputs.artist?.trim() ?? '',
    buildPayload: (item) => {
      const id = normalizeIdentifier(item?.id);
      if (!id) {
        return null;
      }
      return {
        id,
        name: (item?.name ?? '').toString(),
      };
    },
    renderPrimary: (item) => item?.name || item?.id || 'Unknown artist',
    renderSecondary: (item) =>
      item?.id ? `ID: ${item.id}` : 'Qobuz identifier unavailable',
    clearOnSuccess: false,
  },
  album: {
    heading: 'Add albums from Qobuz',
    tagline: 'Search for a release and add it to the queue instantly.',
    idleMessage: 'Provide album and artist names for best results.',
    endpoint: '/api/album-search',
    selectEndpoint: '/api/album-select',
    fields: [
      {
        key: 'title',
        label: 'Album',
        placeholder: 'Album name',
        type: 'search',
        required: false,
      },
      {
        key: 'artist',
        label: 'Artist',
        placeholder: 'Artist name',
        type: 'search',
        required: false,
      },
    ],
    buildQuery: (inputs) =>
      [inputs.title, inputs.artist].map((value) => value?.trim() ?? '').filter(Boolean).join(' '),
    buildPayload: (item) => {
      const id = normalizeIdentifier(item?.id ?? item?.value);
      if (!id) {
        return null;
      }
      return {
        id,
        title: (item?.title ?? '').toString(),
        artist: (item?.artist ?? '').toString(),
        value: (item?.value ?? '').toString(),
        lookup: (item?.lookup ?? '').toString(),
        image: (item?.image ?? '').toString(),
        photo: (item?.photo ?? '').toString(),
      };
    },
    renderPrimary: (item) => item?.title || item?.value || item?.id || 'Unknown album',
    renderSecondary: (item) => {
      const artist = item?.artist ? `Artist: ${item.artist}` : null;
      const year = item?.year ? `Year: ${item.year}` : null;
      return [artist, year].filter(Boolean).join(' · ') || 'Qobuz release';
    },
    clearOnSuccess: true,
  },
  track: {
    heading: 'Add individual tracks',
    tagline: 'Queue a specific song using its Qobuz metadata.',
    idleMessage: 'Combine track, album, and artist names for precise matches.',
    endpoint: '/api/track-search',
    selectEndpoint: '/api/track-select',
    fields: [
      {
        key: 'title',
        label: 'Track',
        placeholder: 'Track name',
        type: 'search',
        required: false,
      },
      {
        key: 'album',
        label: 'Album',
        placeholder: 'Album name',
        type: 'search',
        required: false,
      },
      {
        key: 'artist',
        label: 'Artist',
        placeholder: 'Artist name',
        type: 'search',
        required: false,
      },
    ],
    buildQuery: (inputs) =>
      [inputs.title, inputs.album, inputs.artist]
        .map((value) => value?.trim() ?? '')
        .filter(Boolean)
        .join(' '),
    buildPayload: (item) => {
      const id = normalizeIdentifier(item?.id ?? item?.value);
      if (!id) {
        return null;
      }
      return {
        id,
        title: (item?.title ?? '').toString(),
        album: (item?.album ?? '').toString(),
        artist: (item?.artist ?? '').toString(),
        value: (item?.value ?? '').toString(),
        lookup: (item?.lookup ?? '').toString(),
        album_id: (item?.album_id ?? item?.albumId ?? '').toString(),
        image: (item?.image ?? '').toString(),
        photo: (item?.photo ?? '').toString(),
      };
    },
    renderPrimary: (item) => item?.title || item?.value || item?.id || 'Unknown track',
    renderSecondary: (item) => {
      const parts = [];
      if (item?.artist) {
        parts.push(item.artist);
      }
      if (item?.album) {
        parts.push(item.album);
      }
      return parts.join(' · ') || 'Qobuz track';
    },
    clearOnSuccess: true,
  },
};

const defaultSearchInputs = Object.fromEntries(
  Object.entries(SEARCH_CONFIG).map(([key, config]) => [
    key,
    Object.fromEntries(config.fields.map((field) => [field.key, ''])),
  ]),
);

const makeInitialSearchState = () =>
  Object.fromEntries(
    Object.entries(SEARCH_CONFIG).map(([key, config]) => [
      key,
      {
        inputs: { ...defaultSearchInputs[key] },
        results: [],
        status: 'idle',
        message: config.idleMessage,
      },
    ]),
  );

const BannerStack = ({ banners, onDismiss }) => {
  if (!banners.length) {
    return null;
  }
  return html`
    <div className="banner-stack">
      ${banners.map((banner) => {
        const bannerClass = `banner${banner.isError ? ' is-error' : ''}`;
        const role = banner.isError ? 'alert' : 'status';
        return html`
          <div key=${banner.id} className=${bannerClass} role=${role}>
            <span>${banner.message}</span>
            <button
              type="button"
              aria-label="Dismiss message"
              onClick=${() => onDismiss(banner.id)}
            >
              ×
            </button>
          </div>
        `;
      })}
    </div>
  `;
};

const NeonButton = React.forwardRef(function NeonButton(
  { className = '', variant, children, ...props },
  ref,
) {
  const variantClass = variant === 'danger' ? ' is-danger' : variant === 'ghost' ? ' is-ghost' : '';
  const buttonClass = `reactbits-button${variantClass} ${className}`.trim();
  return html`
    <button ref=${ref} className=${buttonClass} ...${props}>
      ${children}
    </button>
  `;
});

const GlassCard = ({ className = '', padded = true, children }) => {
  const cardClass = `reactbits-card ${padded ? 'reactbits-card--padded' : 'reactbits-card--flush'} ${className}`.trim();
  return html`<section className=${cardClass}>${children}</section>`;
};

const Tabs = ({ value, onChange, options }) =>
  html`
    <div className="reactbits-tabs" role="tablist" aria-label="List selector">
      ${options.map((option) => {
        const isActive = value === option.value;
        const tabClass = `reactbits-tab${isActive ? ' is-active' : ''}`;
        return html`
          <button
            key=${option.value}
            type="button"
            role="tab"
            aria-selected=${isActive}
            className=${tabClass}
            onClick=${() => onChange(option.value)}
          >
            ${option.label}
          </button>
        `;
      })}
    </div>
  `;

const EntryList = ({ kind, label, entries, onRemove, disabled, isRefreshing }) => {
  const countLabel = `${entries.length} entr${entries.length === 1 ? 'y' : 'ies'}`;

  if (!entries.length) {
    return html`
      <${GlassCard}>
        <div className="list-header">
          <h2>${label}</h2>
          <span className="count-pill">${countLabel}</span>
        </div>
        ${isRefreshing
          ? html`<div className="loader" aria-label="Loading entries" />`
          : html`<div className="empty-state">No entries yet.</div>`}
      </${GlassCard}>
    `;
  }

  return html`
    <${GlassCard}>
      <div className="list-header">
        <h2>${label}</h2>
        <span className="count-pill">${countLabel}</span>
      </div>
      <div className="entry-collection">
        ${entries.map((entry, index) =>
          html`<${EntryCard}
            key=${`${kind}-${entry.id || index}`}
            kind=${kind}
            entry=${entry}
            index=${index}
            onRemove=${onRemove}
            disabled=${disabled}
          />`
        )}
      </div>
    </${GlassCard}>
  `;
};

const formatLastChecked = (value) => {
  const normalized = (value ?? '').toString().trim();
  return normalized || 'Never';
};

const EntryCard = ({ kind, entry, index, onRemove, disabled }) => {
  const id = (entry?.id ?? '').toString();
  const name = (entry?.name ?? '').toString();
  const title = (entry?.title ?? '').toString();
  const artist = (entry?.artist ?? '').toString();
  const album = (entry?.album ?? '').toString();
  const lastChecked = formatLastChecked(entry?.last_checked_at);

  let primary = id;
  let subtitle = '';
  let meta = `Last checked: ${lastChecked}`;

  if (kind === 'artist') {
    primary = name || id || 'Artist';
    subtitle = id ? `ID: ${id}` : '';
  } else if (kind === 'album') {
    primary = title || id || 'Album';
    subtitle = [artist && `Artist: ${artist}`, id && `ID: ${id}`].filter(Boolean).join(' · ');
  } else if (kind === 'track') {
    primary = title || id || 'Track';
    subtitle = [artist, album].filter(Boolean).join(' · ');
    meta = [id && `ID: ${id}`, meta].filter(Boolean).join(' · ');
  }

  const albumId = entry?.album_id || entry?.albumId;
  const imageUrl =
    kind === 'artist'
      ? buildArtistPhotoUrl(id)
      : kind === 'album'
      ? buildAlbumPhotoUrl(id)
      : kind === 'track'
      ? buildAlbumPhotoUrl(albumId)
      : '';

  const cardClass = `entry-card${imageUrl ? '' : ' no-media'}`;
  return html`
    <div className=${cardClass}>
      ${imageUrl
        ? html`<div className="entry-thumb">
            <img
              src=${imageUrl}
              alt="Artwork"
              loading="lazy"
              onError=${(event) => (event.currentTarget.style.display = 'none')}
            />
          </div>`
        : null}
      <div className="entry-content">
        <div className="entry-title">${primary}</div>
        ${subtitle ? html`<div className="entry-subtitle">${subtitle}</div>` : null}
        <div className="entry-meta">${meta}</div>
      </div>
      <${NeonButton}
        type="button"
        variant="danger"
        onClick=${() => onRemove(kind, index)}
        disabled=${disabled}
      >
        Remove
      </${NeonButton}>
    </div>
  `;
};

const SearchPanel = ({
  type,
  config,
  state,
  onInputChange,
  onSubmit,
  onSelect,
  disabled,
}) => {
  const handleChange = (key, value) => {
    onInputChange(type, key, value);
  };

  const submit = (event) => {
    event.preventDefault();
    onSubmit(type);
  };

  return html`
    <${GlassCard}>
      <div className="list-header">
        <div>
          <h2>${config.heading}</h2>
          <div className="entry-meta">${config.tagline}</div>
        </div>
      </div>
      <form className="search-form" onSubmit=${submit}>
        <div className="field-grid">
          ${config.fields.map((field) =>
            html`<div className="field-group" key=${field.key}>
              <label htmlFor=${`${type}-${field.key}`}>${field.label}</label>
              <input
                id=${`${type}-${field.key}`}
                type=${field.type || 'text'}
                autoComplete="off"
                placeholder=${field.placeholder}
                value=${state.inputs[field.key] ?? ''}
                required=${field.required}
                onChange=${(event) => handleChange(field.key, event.target.value)}
              />
            </div>`
          )}
        </div>
        <div className="search-actions">
          <${NeonButton} type="submit" disabled=${disabled || state.status === 'loading'}>
            ${state.status === 'loading' ? 'Searching…' : 'Search'}
          </${NeonButton}>
        </div>
        <div className="search-status">${state.message}</div>
        ${state.status === 'loading'
          ? html`<div className="loader" aria-label="Searching" />`
          : state.results.length
          ? html`<ul className="search-results">
              ${state.results.map((item, index) =>
                html`<li key=${`${type}-result-${item.id ?? index}`} className="search-result-card">
                  <div className="search-result-meta">
                    <div className="search-primary">${config.renderPrimary(item)}</div>
                    <div className="search-secondary">${config.renderSecondary(item)}</div>
                  </div>
                  <${NeonButton}
                    type="button"
                    onClick=${() => onSelect(type, item)}
                    disabled=${disabled}
                  >
                    Add
                  </${NeonButton}>
                </li>`
              )}
            </ul>`
          : null}
      </form>
    </${GlassCard}>
  `;
};

function App() {
  const [lists, setLists] = useState(ensureLists(initialState.lists));
  const [selectedList, setSelectedList] = useState(
    LIST_ORDER.includes(initialState.selectedList) ? initialState.selectedList : 'artist',
  );
  const [banners, setBanners] = useState(withBannerIds(initialState.banners));
  const [searchState, setSearchState] = useState(makeInitialSearchState);
  const [pending, setPending] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const labels = useMemo(() => initialState.labels || {}, []);

  const pushBanner = useCallback((message, isError = false) => {
    if (!message) {
      return;
    }
    setBanners((current) => {
      const next = [...current, ...withBannerIds([{ message, isError }])];
      return next.slice(-5);
    });
  }, []);

  const replaceBanners = useCallback((items) => {
    setBanners(withBannerIds(items));
  }, []);

  const refreshLists = useCallback(
    async (targetKind = selectedList) => {
      setRefreshing(true);
      try {
        const response = await fetch('/api/lists?kind=all', {
          headers: { Accept: 'application/json' },
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data?.error || 'Failed to refresh lists.');
        }
        if (data?.lists) {
          setLists(ensureLists(data.lists));
        }
        if (targetKind && LIST_ORDER.includes(targetKind)) {
          setSelectedList(targetKind);
        }
      } catch (error) {
        pushBanner(error.message || 'Unable to refresh lists.', true);
      } finally {
        setRefreshing(false);
      }
    },
    [pushBanner, selectedList],
  );

  useEffect(() => {
    if (initialState.banners?.length) {
      replaceBanners(initialState.banners);
    }
  }, [replaceBanners]);

  const handleDismissBanner = useCallback((id) => {
    setBanners((current) => current.filter((banner) => banner.id !== id));
  }, []);

  const handleInputChange = useCallback((type, key, value) => {
    setSearchState((current) => ({
      ...current,
      [type]: {
        ...current[type],
        inputs: {
          ...current[type].inputs,
          [key]: value,
        },
      },
    }));
  }, []);

  const runSearch = useCallback(async (type) => {
    const config = SEARCH_CONFIG[type];
    if (!config) {
      return;
    }
    const inputs = searchState[type].inputs;
    const query = config.buildQuery(inputs);
    if (!query) {
      setSearchState((current) => ({
        ...current,
        [type]: {
          ...current[type],
          status: 'error',
          message: 'Please provide search details.',
        },
      }));
      return;
    }
    setSearchState((current) => ({
      ...current,
      [type]: {
        ...current[type],
        status: 'loading',
        message: 'Searching…',
        results: [],
      },
    }));

    try {
      const response = await fetch(`${config.endpoint}?q=${encodeURIComponent(query)}`, {
        headers: { Accept: 'application/json' },
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || 'Search failed.');
      }
      const results = Array.isArray(data?.results) ? data.results : [];
      setSearchState((current) => ({
        ...current,
        [type]: {
          ...current[type],
          status: 'ready',
          message: results.length ? 'Select an item to add.' : 'No results found.',
          results,
        },
      }));
    } catch (error) {
      setSearchState((current) => ({
        ...current,
        [type]: {
          ...current[type],
          status: 'error',
          message: error.message || 'Search failed.',
          results: [],
        },
      }));
      pushBanner(error.message || 'Search failed.', true);
    }
  }, [pushBanner, searchState]);

  const handleSelectResult = useCallback(
    async (type, item) => {
      const config = SEARCH_CONFIG[type];
      if (!config) {
        return;
      }
      const payload = config.buildPayload(item);
      if (!payload) {
        pushBanner('The selected item is missing an identifier.', true);
        return;
      }
      setPending(true);
      try {
        const response = await fetch(config.selectEndpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok || data?.success === false) {
          throw new Error(data?.error || data?.message || 'Failed to add entry.');
        }
        await refreshLists(type);
        if (data?.message) {
          pushBanner(data.message, false);
        } else {
          pushBanner(config.successMessage || 'Entry added successfully.', false);
        }
        setSearchState((current) => ({
          ...current,
          [type]: {
            inputs: config.clearOnSuccess ? { ...defaultSearchInputs[type] } : current[type].inputs,
            results: [],
            status: 'ready',
            message: config.clearOnSuccess ? config.idleMessage : 'Entry queued successfully.',
          },
        }));
      } catch (error) {
        pushBanner(error.message || 'Failed to add entry.', true);
        setSearchState((current) => ({
          ...current,
          [type]: {
            ...current[type],
            status: 'error',
            message: error.message || 'Failed to add entry.',
          },
        }));
      } finally {
        setPending(false);
      }
    },
    [pushBanner, refreshLists],
  );

  const handleRemoveEntry = useCallback(
    async (kind, index) => {
      setPending(true);
      try {
        const response = await fetch('/delete', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          body: JSON.stringify({
            list: kind,
            selected: selectedList,
            index,
          }),
        });
        const data = await response.json();
        if (!response.ok || data?.success === false) {
          throw new Error(data?.error || data?.message || 'Failed to remove entry.');
        }
        if (data?.lists) {
          setLists(ensureLists(data.lists));
        }
        if (data?.selected && LIST_ORDER.includes(data.selected)) {
          setSelectedList(data.selected);
        }
        if (data?.banners?.length) {
          replaceBanners(data.banners);
        } else if (data?.message) {
          pushBanner(data.message, false);
        }
      } catch (error) {
        pushBanner(error.message || 'Failed to remove entry.', true);
      } finally {
        setPending(false);
      }
    },
    [pushBanner, replaceBanners, selectedList],
  );

  const handlePhotosAction = useCallback(
    async (endpoint) => {
      setPending(true);
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          body: JSON.stringify({ selected: selectedList }),
        });
        const data = await response.json();
        if (!response.ok || data?.success === false) {
          throw new Error(data?.error || data?.message || 'Action failed.');
        }
        if (data?.lists) {
          setLists(ensureLists(data.lists));
        }
        if (data?.selected && LIST_ORDER.includes(data.selected)) {
          setSelectedList(data.selected);
        }
        if (data?.banners?.length) {
          replaceBanners(data.banners);
        } else if (data?.message) {
          pushBanner(data.message, false);
        }
      } catch (error) {
        pushBanner(error.message || 'Action failed.', true);
      } finally {
        setPending(false);
      }
    },
    [pushBanner, replaceBanners, selectedList],
  );

  const selectedConfig = SEARCH_CONFIG[selectedList];
  const selectedSearchState = searchState[selectedList];
  const listOptions = LIST_ORDER.map((kind) => ({
    value: kind,
    label: labels[kind] || kind.charAt(0).toUpperCase() + kind.slice(1),
  }));

  return html`
    <div className="layout">
      <header className="header-intro">
        <span className="eyebrow">Queue control</span>
        <h1>OrpheusDL Lists</h1>
      </header>

      <${BannerStack} banners=${banners} onDismiss=${handleDismissBanner} />

      <${GlassCard}>
        <div className="list-header">
          <h2>Choose a list to manage</h2>
          <${Tabs} value=${selectedList} onChange=${setSelectedList} options=${listOptions} />
        </div>
        <div className="list-actions">
          <${NeonButton}
            type="button"
            onClick=${() => handlePhotosAction('/download-photos')}
            disabled=${pending}
          >
            Download missing artwork
          </${NeonButton}>
          <${NeonButton}
            type="button"
            variant="danger"
            onClick=${() => handlePhotosAction('/purge-photos')}
            disabled=${pending}
          >
            Purge cached artwork
          </${NeonButton}>
        </div>
      </${GlassCard}>

      ${selectedConfig
        ? html`<${SearchPanel}
            type=${selectedList}
            config=${selectedConfig}
            state=${selectedSearchState}
            onInputChange=${handleInputChange}
            onSubmit=${runSearch}
            onSelect=${handleSelectResult}
            disabled=${pending}
          />`
        : null}

      <${EntryList}
        kind=${selectedList}
        label=${labels[selectedList] || selectedList}
        entries=${lists[selectedList]}
        onRemove=${handleRemoveEntry}
        disabled=${pending}
        isRefreshing=${refreshing}
      />
    </div>
  `;
}

const container = document.getElementById('root');
if (container) {
  const root = createRoot(container);
  root.render(html`<${App} />`);
}
