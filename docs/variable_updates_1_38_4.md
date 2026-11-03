# Formato de escrita de variáveis e desconexão após o inventário

Os logs do aparelho confirmaram inventário inicial, favoritos e consulta de pets,
seguindo com novos pedidos e a mensagem genérica de pacote rejeitado. Encontramos
um erro reproduzível no parser das escritas de variáveis. O log anterior não
registrava o último opcode/evento nem o motivo; por isso não permite afirmar
qual pacote exato encerrou aquela tentativa no aparelho.

## Dois sentidos, dois formatos

`UserVariable.Serialize`, RVA `0x3A86404`, lê Key em `+0x18`, serializa Data
em `+0x20`, obtém o tamanho da chave ASCII e concatena **tamanho + chave + valor**.
O método não escreve o campo UserId em `+0x10`. `UserVariablesFeature.SetVariable`,
RVA `0x35A5B2C`, usa esse serializador nos pedidos do cliente.

`UserVariable.Deserialize`, RVA `0x3A86830`, recebe notificações do servidor e
lê primeiro UserId, depois tamanho da chave, chave e valor. O parser local
assumia esse formato nos dois sentidos. Uma escrita válida e curta do cliente
podia ser rejeitada como truncada ou com tamanho de chave inválido, fechando
a conexão. A leitura de escritas foi separada da leitura das notificações.

| Sentido | Dados de `tbulv` após o envelope do evento |
| --- | --- |
| Cliente → servidor | key length int32 BE + chave ASCII + valor tipado |
| Servidor → cliente | player ID int32 BE + key length int32 BE + chave ASCII + valor tipado |

Exemplo de atualização de RGB no campo `j`:

```text
Cliente:  00 00 00 01 6A 05 10 20 30
Servidor: 00 00 00 07 00 00 00 01 6A 05 10 20 30
```

No exemplo, o ID autenticado de transporte é 7; ele não foi escolhido pelo
cliente. Apenas os campos cosméticos permitidos (`j`, `o`, `hs`) são persistidos.
Tentativas de escrever carteira, inventário ou permissões continuam recusadas.
Uma variável estruturalmente válida mas fora dessa lista não fecha a conexão.
Um pacote que tenta inserir um prefixo de proprietário no pedido é rejeitado.

## Diagnóstico de rejeições

As rejeições agora informam opcode, nome limitado do evento e um motivo fixo de
validação. Não registram o corpo da mensagem nem os tokens da sessão. Exemplo:

```text
TCP rejected packet opcode=8 event="tbulv" reason=Invalid client variable key
```

Esse exemplo é uma rejeição de teste deliberadamente provocada com o formato
antigo, não a atualização legítima do cliente. `TCP unsupported event` indica
uma operação sem implementação; esse log por si só não encerra a conexão.

## Consultas que aparecem depois do inventário

Foram acrescentadas as respostas de leitura abaixo, mantendo o estado local
sem produtos de lootbox nem pets/ovos criados:

| Pedido | Resposta | Schema |
| --- | --- | --- |
| `hair_style`, EventId=0 | `get_hair_styles` | GetHairStyleInventoryResponse, Successful no campo 1, Inventory vazio no campo 2 |
| `lb`, EventId=0 | `lb` | LootBoxInfoResponseMessage, Successful no campo 3, Items vazio no campo 2 |
| `pet`, EventId=19 | `pet`, EventId=24 | PetDetailsResponse com coleção PetDetails vazia |
| `pet`, EventId=24 | `pet`, EventId=32 | EggDetailsResponse com coleção EggDetails vazia |
| `init_day_night` | `G` | DayNightStateResponse: estado inicial local de dia e SkipInterpolation=true |
| `init_pos` | `C` | Snapshot de posições remotas vazio, como stream DEFLATE raw `03 00` |

ToxicBirdHairStyleMechanic.Install (`0x3028438`) registra `get_hair_styles`.
ToxicBirdLootBoxMechanic.Install (`0x3029238`) registra `lb`.
ToxicBirdServer.InstallTransitionDayNightBehavior (`0x23B4784`) registra `G`;
seu callback (`0x23C1F84`) lê DayNightStateResponse.
SendFetchServerStatus (`0x23B57CC`) emite `fetch_events`, `init_pos` e
`init_day_night`. OnPlayerPositionUpdate (`0x23BB03C`) descomprime com
DeflateStream e percorre os estados remotos enquanto há dados. O stream vazio
é válido para a sala isolada sem outros jogadores; não fornece spawn, mapa,
movimento ou uma simulação de mundo. Não há eventos ativos configurados no
servidor local; `fetch_events` não gera notificações de quests inexistentes.

## Verificação e teste no aparelho

Os testes verificam bytes independentes nos dois sentidos, entrada sem owner,
resposta com ID autenticado, recusa de prefixo forjado e preservação da conexão
com ping após uma escrita nativa válida. Outro teste reproduz a sequência de
pedidos posteriores ao inventário, seguida de escrita de variável e ping.
Também são verificados o stream DEFLATE e os campos/IDs das novas respostas.

O diagnóstico `python tools/check_local_character.py` foi ampliado para conferir
esses contratos contra o processo real, incluindo escrita de variável sem
desconexão. A correção não altera o esquema do banco, o APK ou o metadata.

Para atualizar, pare o servidor com Ctrl+C, execute `git pull --ff-only`, inicie
`python server.py` e feche/abra completamente o jogo. Preserve o banco de contas.
O resultado na tela do APK ainda precisa de teste no aparelho. Se houver outra
rejeição, o novo motivo permitirá investigar a validação específica. Compras,
catálogo completo, mundo e serviços ainda não implementados continuam pendentes.
