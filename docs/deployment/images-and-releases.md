# Images, charts and releases

Each release tag `vMAJOR.MINOR.PATCH` (optionally with a pre-release suffix such as `v0.2.0-rc.1`) is published by
`.github/workflows/release.yml`. The workflow runs the full gate (`just check`), builds both images for `linux/amd64` and
`linux/arm64`, pushes them to GitHub Container Registry (GHCR), attests their build provenance, pushes the Helm chart as an OCI
artifact and creates a GitHub Release.

## Published artifacts

| Artifact | Reference | Tags |
| --- | --- | --- |
| Application image (`deploy/Dockerfile`) | `ghcr.io/acarmisc/code-squad` | `X.Y.Z`, `X.Y` (stable only), `latest` (stable only), `sha-<short>` |
| Sandbox image (`deploy/sandbox-node.Dockerfile`) | `ghcr.io/acarmisc/code-squad-sandbox-node` | `X.Y.Z`, `X.Y` (stable only), `latest` (stable only), `sha-<short>` |
| Helm chart | `oci://ghcr.io/acarmisc/charts/code-squad` | `X.Y.Z` (chart `version` and `appVersion` both set to the release) |

Pre-release tags publish only `X.Y.Z-suffix` and `sha-<short>`. They never move `latest` or `X.Y`.

Each release also attaches the chart package (`code-squad-X.Y.Z.tgz`) and `images.txt`, which lists every image reference with
its digest. Pin a digest in production when you need an immutable reference.

## Pulling an image

```bash
docker pull ghcr.io/acarmisc/code-squad:0.1.0
docker pull ghcr.io/acarmisc/code-squad-sandbox-node:0.1.0
```

Both images are multi-architecture. Docker selects the matching platform automatically.

## Verifying provenance

Each image is attested with GitHub build provenance. Verify it before you deploy:

```bash
gh attestation verify oci://ghcr.io/acarmisc/code-squad:0.1.0 --owner acarmisc
```

The command checks that the image was built by the release workflow in this repository. It also works with a digest reference
(`oci://ghcr.io/acarmisc/code-squad@sha256:...`).

## Installing the chart

```bash
helm install code-squad oci://ghcr.io/acarmisc/charts/code-squad --version 0.1.0 -f my-values.yaml
```

The chart defaults to `image.repository: ghcr.io/acarmisc/code-squad` with an empty `image.tag`, so the image tag is the chart's
`appVersion`. The sandbox image is set by `sandbox.image` in `values.yaml`. Read [Helm chart](helm.md) for the required values.

## Making a release

1. Run the bump script. With `--version` it sets `version` and `appVersion` in `deploy/helm/code-squad/Chart.yaml`, the
   sandbox image tag in `values.yaml`, `project.version` in `pyproject.toml`, `__version__` in
   `src/code_squad/__init__.py` and the default image of the GitHub Actions review in `action.yml`, so all of them match
   the tag:

   ```bash
   uv run python scripts/bump_image.py --version 0.2.0 --dry-run
   uv run python scripts/bump_image.py --version 0.2.0
   ```

2. Pass `--tag` only to pin `image.tag`. Leave it out so the image tag follows `appVersion`.
3. Add a `## [0.2.0] - YYYY-MM-DD` section to `CHANGELOG.md`. The release notes are taken from the section whose heading starts
   with `## [0.2.0]`, up to the next `## ` heading. Without that section the release uses generated notes.
4. Run `just check`, merge to `main`, and create an annotated tag on that commit:

   ```bash
   git tag -a v0.2.0 -m "code-squad 0.2.0"
   git push origin v0.2.0
   ```

The `verify` job fails before anything is published if the tag does not match the versions in `pyproject.toml`,
`src/code_squad/__init__.py` or `Chart.yaml`. Its error message names the file that is out of date.

For a pre-release, use a tag such as `v0.2.0-rc.1`. The release is marked as a pre-release, and `latest` is not moved.

## Re-running a release

If a run fails after the tag was pushed, re-run it from the Actions tab with **Run workflow** (`workflow_dispatch`). Enter the
existing tag, for example `v0.2.0`. The workflow checks out that tag, so the images and chart are built from the tagged commit.
Re-runs are safe: the images and chart are pushed again under the same tags, and an existing GitHub Release gets its assets
replaced and its notes updated.

## Making the packages public

GHCR packages are private the first time they are published. To let anyone pull them, change the visibility of each package
once: open the package in the GitHub user or organisation **Packages** page, open **Package settings**, and choose
**Change visibility** to **Public**. Do this for `code-squad`, `code-squad-sandbox-node` and the `charts/code-squad` chart package.

## Air-gapped and mirrored installs

Copy the images and the chart to your own registry, then point the chart at the mirror. Keep the digests from `images.txt`.

```bash
skopeo copy --all docker://ghcr.io/acarmisc/code-squad@sha256:<digest> docker://registry.internal.example/platform/code-squad:0.2.0
skopeo copy --all docker://ghcr.io/acarmisc/code-squad-sandbox-node@sha256:<digest> docker://registry.internal.example/platform/code-squad-sandbox-node:0.2.0
helm pull oci://ghcr.io/acarmisc/charts/code-squad --version 0.2.0
helm push code-squad-0.2.0.tgz oci://registry.internal.example/platform/charts
```

Then set `image.repository`, `sandbox.image` and, if the mirror is private, `imagePullSecrets` in your values file. The examples
in `deploy/helm/code-squad/values-examples/` show these settings for air-gapped clusters.
