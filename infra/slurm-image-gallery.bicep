targetScope = 'resourceGroup'

param location string
param galleryName string
param imageDefinitionName string
param environment string

var tags = {
  project: 'genomics-variant-accelerator'
  component: 'private-slurm-image'
  environment: environment
}

resource gallery 'Microsoft.Compute/galleries@2024-03-03' = {
  name: galleryName
  location: location
  tags: tags
  properties: {
    description: 'Private Slurm/AMLFS images for the genomics accelerator.'
  }
}

resource definition 'Microsoft.Compute/galleries/images@2024-03-03' = {
  parent: gallery
  name: imageDefinitionName
  location: location
  tags: tags
  properties: {
    osType: 'Linux'
    osState: 'Generalized'
    hyperVGeneration: 'V2'
    identifier: {
      publisher: 'genomics-variant-accelerator'
      offer: 'private-slurm'
      sku: 'ubuntu-24_04-amlfs'
    }
    features: [
      {
        name: 'SecurityType'
        value: 'TrustedLaunchSupported'
      }
    ]
  }
}

output imageDefinitionId string = definition.id
