# Mundo e sala local — 1.38.4

## Evidência no aparelho

O log com a revisão `194b769` confirma que o cliente passou pelas consultas de
inventário, horário, lojas, cabelo, lootboxes e cache de pets. Depois enviou
`pet` com EventId 13, uma escrita de variável, `C` com 18 bytes e `vhc` com
corpos de zero e dois bytes. O cliente encerrou o TCP e voltou à tela inicial,
sem a rejeição de pacote observada antes. Não há nesse log uma exceção Unity,
portanto ele não identifica sozinho a causa exata do retorno.

O novo código trata essas consultas e conserva o estado transitório da sala.
Não há confirmação visual posterior no APK durante o desenvolvimento em nuvem.

## Cena, spawn e avatar

O cliente escolhe o spawn a partir de transforms e serviços da cena Unity:

- `OnboardingSpawnLocationInitStep.MoveNext`, RVA `0x2EBD4B8`, resolve o
  PlayerController e chama SetCharacterPosition/SetCharacterRotation.
- `CentralSquareSpawnLocationInitStep.MoveNext`, `0x2EBC0D8`, chama
  WorldTeleportCenter.TeleportToATownSquarePosition.
- `HomeSpawnLocationInitStep.MoveNext`, `0x2EBC6BC`, usa
  HomeController.GetPlayerSpawnSlot.

O servidor não precisa inventar coordenadas para esses transforms. Ele envia
o perfil/aparência, a camada inicial de mundo (`A`, IntVariable 0), visibilidade
(`I`, BoolVariable false) e dono da casa atual (`r`, StringVariable vazia,
representando estar fora de uma casa). A roupa continua vindo dos defaults
nativos e das escolhas persistidas em SQLite. O envio de uma posição pelo
cliente indica execução de estado do avatar; não prova que sua imagem já
ficou visível ou que a tela de carregamento terminou.

Cada conexão tem uma sala individual de ID 1. O número de transporte não é o
UUID da conta. Os IDs simultâneos são distintos e ficam entre 1 e 255, pois
as rotinas nativas de movimento remoto leem um byte para esse ID. São liberados
ao encerrar a conexão. Sala compartilhada e transmissão entre jogadores ainda
não estão implementadas. Os 32 slots de conexão existentes continuam limitados.

## Movimento e camada

| Pedido do cliente | Corpo após o envelope ToxicBird | Evidência |
| --- | --- | --- |
| `C` | teleport byte, sequence byte, X/Y/Z/rotation float32 big-endian: 18 bytes | GetPositionStateObject `0x2DE3004`, SendLocalPlayerStatePositionUpdateMessage `0x23BC0F4` |
| `PL` | layer int32 big-endian, sequence byte, X/Y/Z/rotation float32 big-endian: 21 bytes | GetLayerObject `0x2DE3194`, SendLocalPlayerLayerUpdateMessage `0x23BC204` |

O primeiro byte de `C` é uma flag de teleporte; não é um ID de proprietário.
A identidade vem da conexão autenticada. As posições precisam ser finitas,
o tamanho é exato e a sequência byte pode passar de 255 para 0. O TCP mantém
a ordem de entrega. Não há persistência de coordenadas em SQLite: a próxima
entrada usa novamente o spawn escolhido pelo APK.

O estado fica em LocalWorldSession durante a permanência na sala. Sair remove
posição, flags e slots, preservando conta, nome e aparência. Uma nova entrada
começa com estado transitório limpo. Pings continuam recebendo Pong.

As escritas `tbulv` das flags `e`, `g`, `h`, `hrsl`, `mg` e `eb` aceitam apenas
BoolVariable com 0 ou 1. São estados visuais transitórios (quest, poder, edição,
salão, microgame e carregamento), não concessões de itens ou recompensas.
`he` permite remover o holdable (IntVariable 0), pois ainda não há holdables
concedidos na política de inventário local. Carteira, inventário, identidade,
papéis e visibilidade continuam sendo definidos pelo servidor.

O servidor não devolve os 18 bytes de `C` como se fossem uma atualização remota:
o leitor nativo de respostas (`OnPlayerPositionUpdate`, `0x23BB03C`) espera
DEFLATE raw contendo registros com ID do jogador, sequência e quatro floats.
`init_pos` continua devolvendo o stream vazio `03 00`, válido para uma sala sem
outros jogadores. Não é uma mensagem de spawn próprio.

## Consultas necessárias após o inventário

| Pedido | Resposta no evento | Campos Protobuf |
| --- | --- | --- |
| `vhc`, EventId 0, corpo vazio | `vhc` | GetVehiclesResponse: IsSuccess no campo 2; lista Vehicles no campo 3, vazia |
| `vhc`, EventId 5 | `vhc` | InitializeVehiclesResponse: EventId 1 = 5; VehiclePositions no campo 2, vazia; não tem flag de sucesso |
| `pet`, EventId 13 | `pet` | PetEvolutionTableResponse: EventId 1 = 19; Evolutions 2 e PetDonateReward 3, vazias |
| `slot_interaction`, EventId 2 | `n` | SlotCacheResponse: EventType 1 = 0; SlotIds 2 e SlotOccupants 3, vazios inicialmente |
| `slot_interaction`, EventId 3 | `n` quando há remoções | Limpa os slots do solicitante; RemoveFromSlotCacheResponse: EventType 1 = 2, SlotIds 2 |

`ToxicBirdVehicleMechanic.OnVehicleResponse` (`0x303CC10`) faz o dispatch pelos
IDs das respostas de veículo. `SendGetPetEvolutionTable` (`0x2E06FCC`) envia
o pedido 13. Não há veículos/pets criados nem compras implementadas nesta etapa.

`ToxicBirdServer.SendGetCache` (`0x23C06E4`) escreve EventId 2 e o UUID no
**campo 3** de SlotCacheRequest. O campo 2 é o ID numérico do slot.
InstallSlotCacheBehavior (`0x23B4FE4`) registra `n`, cujo callback
`0x23C1E38` distribui cache, atualização, remoção e ocupação.

Ocupar/liberar slots locais também atualiza o cache em memória. A ocupação
devolve OccupySlotCacheResponse (EventType 3, IsFree 2 e Occupant 3), seguida
de UpdateSlotCacheResponse (EventType 1, SlotId 2 e UserId 3). O backend usa
a conta autenticada; não aceita operar em nome de outro usuário. Os IDs
int32 zero e negativos são preservados nas listas. O estado é isolado por
conexão e limitado a 256 slots. Interações em casas de outros jogadores
dependem da implementação futura de casas/salas compartilhadas.

## Diagnóstico e validação

O primeiro movimento gera `TCP world position received; local avatar is sending state`.
O encerramento informa se uma posição chegou, a quantidade de pacotes e a duração
da sessão, sem imprimir coordenadas ou tokens. Isso permite distinguir um
cliente que não iniciou seu avatar de um que iniciou e falhou em etapa posterior.

Em `/health`, `worldSessionImplemented` descreve esta sala individual;
`sharedRoomsImplemented` e `worldImplemented` permanecem false para indicar
que transmissão entre jogadores e simulação completa ainda não existem.

Os testes exercitam os bytes nativos de movimento, formatos distintos nos dois
sentidos, respostas de veículos/pets, cache de slots, validações, autenticação,
saída/reentrada, isolamento de conexões e persistência de conta. O diagnóstico
`python tools/check_local_character.py` verifica a nova sequência no processo
real usando coordenadas sintéticas, que não são coordenadas recuperadas do mapa.
O relatório está em [world-verification.json](world-verification.json).

Atualize o Python com `git pull --ff-only`, reinicie o servidor e feche/abra o
jogo. Preserve o APK e o banco existentes. Se voltar ao início, o log completo
da nova tentativa e, quando disponível, a linha Unity
`[GameController] Game initialization failed: ...` identificarão a próxima
dependência. O monitor de inicialização (`0x2165B50`) contém esse log e o
retorno à cena de login. Não se infere uma exceção específica apenas de EOF.
