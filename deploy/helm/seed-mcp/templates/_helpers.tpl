{{- define "seed-mcp.name" -}}
{{- printf "%s-seed-mcp" .Release.Name | trunc 52 | trimSuffix "-" -}}
{{- end -}}

{{- define "seed-mcp.proxy" -}}
{{- if eq .Values.service.mode "apig-staging" -}}
{{- .Files.Get "files/Caddyfile.apig-staging" -}}
{{- else -}}
{{- .Files.Get "files/Caddyfile" -}}
{{- end -}}
{{- end -}}

{{- define "seed-mcp.selector" -}}
app.kubernetes.io/name: seed-mcp
app.kubernetes.io/instance: {{ .Release.Name | quote }}
{{- end -}}

{{- define "seed-mcp.resources" -}}
requests:
  cpu: {{ printf "%vm" .cpuRequestMillis | quote }}
  memory: {{ printf "%vMi" .memoryRequestMiB | quote }}
  ephemeral-storage: "64Mi"
limits:
  cpu: {{ printf "%vm" .cpuLimitMillis | quote }}
  memory: {{ printf "%vMi" .memoryLimitMiB | quote }}
  ephemeral-storage: "256Mi"
{{- end -}}

{{- define "seed-mcp.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}
