metadata description = 'Separate workload identities so ingestion, staging and processing grants stay independent.'

param location string
param tags object
param suffix string

resource ingestion 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-genomics-ingestion-${suffix}'
  location: location
  tags: tags
}

resource staging 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-genomics-staging-${suffix}'
  location: location
  tags: tags
}

resource pipeline 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-genomics-pipeline-${suffix}'
  location: location
  tags: tags
}

output ingestionPrincipalId string = ingestion.properties.principalId
output stagingPrincipalId string = staging.properties.principalId
output pipelinePrincipalId string = pipeline.properties.principalId
output ingestionClientId string = ingestion.properties.clientId
output stagingClientId string = staging.properties.clientId
output pipelineClientId string = pipeline.properties.clientId
output resourceIds array = [
  ingestion.id
  staging.id
  pipeline.id
]
output ingestionResourceId string = ingestion.id
output stagingResourceId string = staging.id
