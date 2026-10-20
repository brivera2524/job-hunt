# Job Hunt plugin for Claude

An honest, mostly hands-off job search: finds openings twice a day, applies with a resume tailored to each posting and checked against your verified dossier, reads your email to keep your tracker current, and reviews what's working every week. Details are in [plugins/job-hunt/README.md](plugins/job-hunt/README.md).

## Install (claude.ai or the Claude desktop app)

1. Go to **Customize → Plugins → Add → Add marketplace** and enter `brivera2524/job-hunt`.
2. Turn on **Sync automatically** for the marketplace so you get updates as they're pushed.
3. Add the **job-hunt** plugin from the list.
4. Install the [Claude in Chrome](https://claude.com/chrome) extension (applications are filled in your own Chrome).
5. Open a new chat and say **"set up my job search"**.

Needs a paid Claude plan. After an update that changes the tracker page, say **"refresh job hunt setup"** once so your Job Search HQ picks it up.

## Install (Claude Code)

```
/plugin marketplace add brivera2524/job-hunt
/plugin install job-hunt@brivera-plugins
```

## Updates

The plugin has no fixed version number, so every push to `main` is a new version. See [CHANGELOG.md](CHANGELOG.md).
