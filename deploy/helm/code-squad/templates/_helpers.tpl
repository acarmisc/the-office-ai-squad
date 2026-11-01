{{/*
Namespace used for every rendered object.
*/}}
{{- define "code-squad.namespace" -}}
{{- .Values.global.namespaceOverride | default .Release.Namespace -}}
{{- end -}}

{{/*
Space-separated list of agent ids. Order matters for ORCHESTRATOR_SPECIALIST_URLS.
*/}}
{{- define "code-squad.agentIds" -}}
michael jim angela dwight darryl pam
{{- end -}}

{{/*
Image reference: repository plus tag, defaulting to Chart.appVersion.
*/}}
{{- define "code-squad.image" -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) -}}
{{- end -}}

{{/*
Labels shared by every object of the release.
*/}}
{{- define "code-squad.labels" -}}
app.kubernetes.io/name: code-squad
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: code-squad
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
{{- end -}}

{{/*
Per-agent labels. Input: dict "id" <agent id> "root" <root context>.
*/}}
{{- define "code-squad.agentLabels" -}}
{{ include "code-squad.labels" .root }}
app.kubernetes.io/component: {{ .id }}
{{- end -}}

{{/*
Per-agent selector labels (immutable once a Deployment exists). Input: dict "id", "root".
*/}}
{{- define "code-squad.agentSelectorLabels" -}}
app.kubernetes.io/name: code-squad
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .id }}
{{- end -}}

{{/*
Object name for an agent: code-squad-<id>. Input: dict "id", "root".
*/}}
{{- define "code-squad.agentName" -}}
{{- printf "code-squad-%s" .id -}}
{{- end -}}

{{/*
ServiceAccount name for an agent. Input: dict "id", "root".
*/}}
{{- define "code-squad.serviceAccountName" -}}
{{- if .root.Values.serviceAccount.create -}}
{{- include "code-squad.agentName" . -}}
{{- else -}}
{{- .root.Values.serviceAccount.name | default "default" -}}
{{- end -}}
{{- end -}}

{{/*
Comma-separated specialist URLs for michael, built from enabled agents other than michael.
Format: jim=http://code-squad-jim.<ns>.svc:8080,angela=...
*/}}
{{- define "code-squad.specialistUrls" -}}
{{- $ns := include "code-squad.namespace" . -}}
{{- $urls := list -}}
{{- range $id := splitList " " (include "code-squad.agentIds" .) -}}
{{- if and (ne $id "michael") (index $.Values.agents $id).enabled -}}
{{- $urls = append $urls (printf "%s=http://code-squad-%s.%s.svc:8080" $id $id $ns) -}}
{{- end -}}
{{- end -}}
{{- join "," $urls -}}
{{- end -}}

{{/*
Comma-separated webhook providers for michael (WEBHOOK_PROVIDERS), from webhooks.*.enabled.
Empty when neither provider is enabled, which registers no webhook route.
*/}}
{{- define "code-squad.webhookProviders" -}}
{{- $providers := list -}}
{{- if .Values.webhooks.gitlab.enabled -}}
{{- $providers = append $providers "gitlab" -}}
{{- end -}}
{{- if .Values.webhooks.github.enabled -}}
{{- $providers = append $providers "github" -}}
{{- end -}}
{{- join "," $providers -}}
{{- end -}}

{{/*
Read-only devops rules shared by the namespaced Role and the ClusterRole.
*/}}
{{- define "code-squad.devopsReadRules" -}}
- apiGroups: [""]
  resources: ["pods", "pods/log", "events", "services", "endpoints", "configmaps"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments", "replicasets", "statefulsets", "daemonsets", "controllerrevisions"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["metrics.k8s.io"]
  resources: ["pods"]
  verbs: ["get", "list"]
{{- end -}}

{{/*
One egress rule to a set of CIDRs on a set of ports. Input: dict "cidrs" list, "ports" list.
Renders nothing when cidrs is empty (an empty "to" would mean "any destination").
*/}}
{{- define "code-squad.egressCIDRRule" -}}
{{- if .cidrs -}}
- to:
    {{- range .cidrs }}
    - ipBlock:
        cidr: {{ . | quote }}
    {{- end }}
  ports:
    {{- range $.ports }}
    - protocol: TCP
      port: {{ . }}
    {{- end }}
{{- end -}}
{{- end -}}
