metadata description = 'Data Factory Copy pipeline staging complete landing-zone files into object storage (task 3.1).'

param location string
param tags object
param name string
param landingAccountId string
param landingAccountName string
param landingShareName string
param lakeAccountId string
param lakeAccountName string
param lakeFilesystem string

@description('Reads the landing share. Landing access stays limited to the ingestion identity.')
param ingestionIdentityId string

@description('Writes staged artifacts. Holds the only write grant on the lake.')
param stagingIdentityId string

resource factory 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${ingestionIdentityId}': {}
      '${stagingIdentityId}': {}
    }
  }
  properties: {
    publicNetworkAccess: 'Disabled'
  }
}

resource managedNetwork 'Microsoft.DataFactory/factories/managedVirtualNetworks@2018-06-01' = {
  parent: factory
  name: 'default'
  properties: {}
}

resource runtime 'Microsoft.DataFactory/factories/integrationRuntimes@2018-06-01' = {
  parent: factory
  name: 'AutoResolveIntegrationRuntime'
  properties: {
    type: 'Managed'
    managedVirtualNetwork: {
      type: 'ManagedVirtualNetworkReference'
      referenceName: managedNetwork.name
    }
    typeProperties: {
      computeProperties: {
        location: 'AutoResolve'
      }
    }
  }
}

resource landingEndpoint 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = {
  parent: managedNetwork
  name: 'landing-file'
  properties: {
    privateLinkResourceId: landingAccountId
    groupId: 'file'
  }
}

resource lakeEndpoint 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = {
  parent: managedNetwork
  name: 'lake-dfs'
  properties: {
    privateLinkResourceId: lakeAccountId
    groupId: 'dfs'
  }
}

resource ingestionCredential 'Microsoft.DataFactory/factories/credentials@2018-06-01' = {
  parent: factory
  name: 'ingestion'
  properties: {
    type: 'ManagedIdentity'
    typeProperties: {
      resourceId: ingestionIdentityId
    }
  }
}

resource stagingCredential 'Microsoft.DataFactory/factories/credentials@2018-06-01' = {
  parent: factory
  name: 'staging'
  properties: {
    type: 'ManagedIdentity'
    typeProperties: {
      resourceId: stagingIdentityId
    }
  }
}

resource landingLink 'Microsoft.DataFactory/factories/linkedServices@2018-06-01' = {
  parent: factory
  name: 'LandingShare'
  properties: {
    type: 'AzureFileStorage'
    connectVia: {
      type: 'IntegrationRuntimeReference'
      referenceName: runtime.name
    }
    typeProperties: {
      serviceEndpoint: 'https://${landingAccountName}.file.${az.environment().suffixes.storage}/'
      fileShare: landingShareName
      credential: {
        type: 'CredentialReference'
        referenceName: ingestionCredential.name
      }
    }
  }
  dependsOn: [
    landingEndpoint
  ]
}

resource lakeLink 'Microsoft.DataFactory/factories/linkedServices@2018-06-01' = {
  parent: factory
  name: 'ObjectStore'
  properties: {
    type: 'AzureBlobFS'
    connectVia: {
      type: 'IntegrationRuntimeReference'
      referenceName: runtime.name
    }
    typeProperties: {
      url: 'https://${lakeAccountName}.dfs.${az.environment().suffixes.storage}/'
      credential: {
        type: 'CredentialReference'
        referenceName: stagingCredential.name
      }
    }
  }
  dependsOn: [
    lakeEndpoint
  ]
}

resource landingFile 'Microsoft.DataFactory/factories/datasets@2018-06-01' = {
  parent: factory
  name: 'LandingFile'
  properties: {
    type: 'Binary'
    linkedServiceName: {
      type: 'LinkedServiceReference'
      referenceName: landingLink.name
    }
    parameters: {
      folderPath: {
        type: 'String'
      }
      fileName: {
        type: 'String'
      }
    }
    typeProperties: {
      location: {
        type: 'AzureFileStorageLocation'
        folderPath: {
          value: '@dataset().folderPath'
          type: 'Expression'
        }
        fileName: {
          value: '@dataset().fileName'
          type: 'Expression'
        }
      }
    }
  }
}

resource stagedFile 'Microsoft.DataFactory/factories/datasets@2018-06-01' = {
  parent: factory
  name: 'StagedFile'
  properties: {
    type: 'Binary'
    linkedServiceName: {
      type: 'LinkedServiceReference'
      referenceName: lakeLink.name
    }
    parameters: {
      folderPath: {
        type: 'String'
      }
      fileName: {
        type: 'String'
      }
    }
    typeProperties: {
      location: {
        type: 'AzureBlobFSLocation'
        fileSystem: lakeFilesystem
        folderPath: {
          value: '@dataset().folderPath'
          type: 'Expression'
        }
        fileName: {
          value: '@dataset().fileName'
          type: 'Expression'
        }
      }
    }
  }
}

// The caller supplies only files the inventory reports complete; the pipeline copies exactly that set.
resource stagePipeline 'Microsoft.DataFactory/factories/pipelines@2018-06-01' = {
  parent: factory
  name: 'StageCompleteFiles'
  properties: {
    parameters: {
      completeFiles: {
        type: 'Array'
        defaultValue: []
      }
    }
    activities: [
      {
        name: 'StageEachCompleteFile'
        type: 'ForEach'
        typeProperties: {
          items: {
            value: '@pipeline().parameters.completeFiles'
            type: 'Expression'
          }
          isSequential: false
          batchCount: 8
          activities: [
            {
              name: 'CopyCompleteFile'
              type: 'Copy'
              inputs: [
                {
                  type: 'DatasetReference'
                  referenceName: landingFile.name
                  parameters: {
                    folderPath: {
                      value: '@item().sourceFolder'
                      type: 'Expression'
                    }
                    fileName: {
                      value: '@item().fileName'
                      type: 'Expression'
                    }
                  }
                }
              ]
              outputs: [
                {
                  type: 'DatasetReference'
                  referenceName: stagedFile.name
                  parameters: {
                    folderPath: {
                      value: '@item().destinationFolder'
                      type: 'Expression'
                    }
                    fileName: {
                      value: '@item().fileName'
                      type: 'Expression'
                    }
                  }
                }
              ]
              typeProperties: {
                source: {
                  type: 'BinarySource'
                  storeSettings: {
                    type: 'AzureFileStorageReadSettings'
                    recursive: false
                  }
                }
                sink: {
                  type: 'BinarySink'
                  storeSettings: {
                    type: 'AzureBlobFSWriteSettings'
                  }
                }
                validateDataConsistency: true
              }
            }
          ]
        }
      }
    ]
  }
}

output factoryName string = factory.name
output pipelineName string = stagePipeline.name
output managedPrivateEndpointNames array = [
  landingEndpoint.name
  lakeEndpoint.name
]
