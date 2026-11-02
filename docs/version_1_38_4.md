# Etapa 1 — compatibilidade do lobby para 1.38.4

## Resultado desta etapa

Implementado um lobby HTTP local com a rota efetivamente reconstruída do cliente:
`POST /lobby/allocation`. O protocolo aceito é `0.2.49`, presente nos arquivos
enviados para o projeto. `1.38.4` é a versão do aplicativo indicada pelo usuário.

O backend aceita uma alocação genérica desse protocolo e devolve o destino
configurado. O módulo não inicia TCP/UDP de gameplay, não autentica sessões e
não carrega o mundo. Uma alocação aceita remove a rejeição de protocolo neste
lobby; não demonstra entrada funcional no cliente Android.

## Evidência recuperada

Fonte: `dump.cs` SHA-256
`aa2509394fe6dfb514135b0b70019729c5df6b01f677eba5e61965a7ae282b2c`,
`libil2cpp.so` ARM64 SHA-256
`32e8e598619d9ff1136a184b39b0c93b19a461b56ef612bb56871072765e6fbe`,
`global-metadata.dat` SHA-256
`f2e909fe0d8668da323805d2a8cef2d69068b6f114322aedd0d2b3452a24ffde`.

| Componente | Declaração / RVA | Evidência |
|---|---|---|
| Protocolo | `PlayKids.XD.Config`, dump:265809/265812 | `GameServerProtocolVersion = "0.2.49"`. |
| Pedido | `GenericAllocateRequest`, dump:176602 | Campos `userToken`, `gameServerProtocolVersion`, `isPrivate`. |
| Caminho | `get_ApiPath`, RVA `0x30ACC7C` | Carrega o literal `/lobby/allocation` em `0x30ACC90` e o devolve em `0x30ACCAC`. |
| Corpo | `ToJsonBody`, RVA `0x30ACCBC` | Chama `UnityEngine.JsonUtility.ToJson`; os campos privados são `[SerializeField]`. |
| HTTP | `LobbyAPI.<AllocatePlayerWebRequest>d__4.MoveNext`, RVA `0x30ADC04` | Concatena host e caminho; usa `POST`, UTF-8 e `Content-Type: application/json`. |
| Resposta | `PlayerAllocationResponse`, dump:298253; `CreateFromJSON` RVA `0x2E0BEB8` | Usa `UnityEngine.JsonUtility.FromJson<PlayerAllocationResponse>`. |
| Seleção de ramo | `ProcessLobbyResponse`, RVA `0x30ACE20` | Lê `successful` em `0x30ACE94`; falso chama tratamento de erro, verdadeiro chama sucesso. |
| Transporte HTTP | `LobbyRequestSuccessful`, RVA `0x30AD0A0` | Exige status 200–299 e corpo não vazio. |
| Rejeição de protocolo | `ConnectionController.HandlePlayerAllocationError`, RVA `0x202AC20` | Em `0x202B000–0x202B020`, compara `failureReason` com `GAME_SERVER_PROTOCOL_VERSION_MISMATCH`; prepara as mensagens `IncompatibleVersionMessageKey` e `CheckYourGameVersionMessageKey`. |
| Popup | `LoginUIController.OnMessageReceived(ConnectionErrorMessage)`, RVA `0x284944C` | Lê `ShouldOpenPopup` em `0x28494EC`; quando aplicável chama `VersionUpdateNeededController.BroadcastMessage` em `0x2849514`. |
| Tipo de servidor | `ConnectionController.ServerTypeEnum`, dump:292234 | `DEFAULT = 0`; `OnAllocationSuccess` converte o texto retornado em enum. |

Esse é um caminho confirmado no binário que pode causar o pedido de atualização.
Ainda não foi capturada a resposta do aparelho para provar que esse seja o erro
exato observado pelo usuário. O popup também depende do fluxo de conexão e dos
campos da mensagem interna.

Não foi criada uma rota fictícia `/version`. A comparação
`AppVersionUtils.IsNewerVersion` aparece no sistema de atualização opcional
`SoftUpdateData.HasUpdateAvailable`; mudar apenas essa comparação não resolve
a rejeição do lobby demonstrada acima.

## Contrato implementado

Pedido representativo:

```http
POST /lobby/allocation
Content-Type: application/json

{"userToken":"local-test","gameServerProtocolVersion":"0.2.49","isPrivate":false}
```

Resposta de alocação aceita, com o destino dos exemplos:

```json
{
  "successful": true,
  "failureReason": "",
  "failureDescription": "",
  "gameServerId": "local-1.38.4",
  "gameServerAddress": "127.0.0.1",
  "gameServerHosts": ["127.0.0.1"],
  "gameServerPort": 7000,
  "gameServerUdpPort": 0,
  "gameServerEngine": "ToxicBird",
  "gameServerType": "DEFAULT",
  "gameServerOwnerId": ""
}
```

`gameServerId`, o rótulo `gameServerEngine`, o endereço e as portas são escolhas
desta implantação local, não valores de uma resposta original capturada. Os
nomes dos campos e seus tipos vêm do DTO. O fluxo nativo examinado cria o
adapter `ToxicBirdServer` (`CreateNewServerInstance`, RVA `0x202A1C0`).

Um protocolo diferente retorna **HTTP 200** com `successful: false` e
`failureReason: "GAME_SERVER_PROTOCOL_VERSION_MISMATCH"`. Isso permite ao
cliente alcançar o tratamento JSON identificado; HTTP 426 não cumpriria o teste
de sucesso HTTP que precede essa leitura.

Erros locais de JSON/validação usam `INVALID_REQUEST`; recursos de sala ainda
fora desta etapa usam `UNSUPPORTED_ALLOCATION`. Esses nomes são decisões locais,
não constantes recuperadas do servidor original. O serviço só atende alocação
genérica de mundo padrão. Não anuncia suporte a salas privadas, visitas a
usuários ou atividades.

O pedido não carrega `appVersion`: somente esse contrato não distingue 1.38.4 de
outra build que compartilhe o mesmo protocolo. Não foi inventado um campo
obrigatório de versão que o cliente original não envia. `userToken` é recebido
como texto opaco; sua validade de sessão será tratada na etapa correspondente.

## Redirecionamento do lobby no metadata

O utilitário `tools/redirect_lobby_metadata.py` só aceita o hash do metadata
analisado. Ele cria outro arquivo e altera apenas estes literais:

| Índice do literal | Valor original |
|---:|---|
| 19283 | `https://pkxd-lobby.aftvrsys.com` |
| 19284 | `https://pkxd-lobby.playpkxd.com` |

Os dois podem apontar para `http://127.0.0.1:8080`. O tamanho total do arquivo,
os offsets das tabelas, os tipos, os métodos e os demais literais permanecem
preservados. Só os comprimentos desses dois registros e os respectivos espaços
de dados são alterados; sobras recebem zero. Contas, Firebase e hosts de homolog
permanecem como no original. Uma URL maior que o espaço disponível é rejeitada.

No Termux, na raiz do projeto e com seu metadata original acessível:

```sh
mkdir -p output
python tools/redirect_lobby_metadata.py \
  /caminho/global-metadata.dat output/global-metadata.local.dat
```

O caminho de saída deve estar livre. Para verificar o resultado padrão:

```sh
sha256sum output/global-metadata.local.dat
# 430b63f12b3b151914840253a8ce86c263d7730d286280bd115c77170833c133
```

Para o jogo ler essa alteração, ela precisa ser incorporada ao APK correto no
lugar de `global-metadata.dat`; não basta executar o script no Termux. Um APK
modificado também precisa ser empacotado e assinado corretamente. Essa
integração não foi executada: o APK/manifesto não foi fornecido. Não se deve
desinstalar o aplicativo existente nem substituir dados sem preservá-los.

O exemplo usa HTTP em loopback. Se a política de rede desse APK bloquear tráfego
sem TLS, será necessário definir uma configuração local compatível e verificar
a política no manifesto; o utilitário não desativa validação de certificados.
`127.0.0.1` só aponta para o Termux quando jogo e servidor estão no mesmo aparelho.

## Executar e verificar

```sh
pkg install python curl
python -m pkxd_server --port 8080 --game-port 7000
```

`--game-port 7000` define o destino anunciado para a futura etapa de transporte.
Não abre essa porta. O servidor desta etapa escuta HTTP em `127.0.0.1:8080`.
Em outra sessão do Termux:

```sh
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/lobby/allocation \
  -H 'Content-Type: application/json' \
  --data '{"userToken":"local-test","gameServerProtocolVersion":"0.2.49","isPrivate":false}'
```

`/health` é um diagnóstico local próprio, não uma API recuperada do jogo.
Para encerrar o lobby, use Ctrl+C.

## Validação executada e limite atual

- 16 testes de HTTP/contrato e alteração de metadata passaram em Python 3.12.14.
- A entrada por `python -m pkxd_server` foi iniciada, recebeu GET de saúde e POST
  de alocação, e encerrou com código 0 após SIGINT.
- A cópia modificada real passou pela validação estrutural independente do
  metadata: 120 imagens, 21.887 tipos, 146.636 métodos, todas as tabelas íntegras.
- Uma comparação de todos os 23.281 literais encontrou mudanças somente nos
  índices 19283 e 19284.
- O cliente Android não foi executado e a política de rede/assinatura do APK
  não foi inspecionada. Não se declara a versão liberada no aparelho, o login
  concluído nem entrada no mundo a partir desses testes de backend.

Testes reproduzíveis na raiz do repositório:

```sh
python -m unittest discover -s tests -v
```
