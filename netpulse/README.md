# Netpulse

Monitor leve de conectividade para homelab, rodando 24x7 em Docker, com retenção separada entre logs brutos e histórico agregado para gráficos.

## O Que Ele Faz

- Executa checagens periódicas de conectividade IP usando `TCP connect` em alvos públicos confiáveis.
- Executa consultas DNS diretas contra resolvedores diferentes, como Cloudflare e Google.
- Classifica cada coleta como:
  - `healthy`: internet e DNS funcionando
  - `dns_issue`: conectividade IP existe, mas DNS falhou
  - `offline`: sem conectividade IP e sem DNS
  - `degraded`: comportamento parcial ou inconsistente
- Persiste tudo em SQLite local.
- Remove automaticamente logs brutos por idade e também por limite de tamanho.
- Mantém agregados horários e diários por mais tempo para preservar os gráficos.
- Exibe painel web com status atual, contagem por período e incidentes recentes.
- Permite alterar a política de retenção direto pelo frontend.

## Por Que Não Só Ping?

O `ping` puro é simples, mas pode gerar falso positivo ou falso negativo em alguns cenários:

- ICMP pode ser limitado, priorizado diferente ou bloqueado.
- Se `google.com` falhar, você não sabe se foi a internet ou apenas DNS.

Por isso a stack separa duas dimensões:

- conectividade IP: `1.1.1.1:53` e `8.8.8.8:53`
- resolução DNS: consulta `google.com` nos resolvedores `1.1.1.1` e `8.8.8.8`

Assim fica mais fácil responder:

- a internet caiu mesmo?
- só o DNS local/provedor falhou?
- um resolvedor caiu e o outro continuou funcionando?

## Estrutura

```text
netpulse/
├── app/
├── data/
├── static/
├── templates/
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── README.md
└── requirements.txt
```

## Subindo

```bash
cd /Volumes/homeX/git/homelab/netpulse
cp .env.example .env
docker compose up -d --build
```

Depois acesse:

- Dashboard: [http://localhost:8097](http://localhost:8097)

## Reparo Do Banco

Se você subir uma versão nova com tabelas agregadas adicionais e quiser reconstruir o histórico sem perder o banco persistente, rode:

```bash
cd /Volumes/homeX/git/homelab/netpulse
python3 scripts/repair_db.py
```

O script:

- lê automaticamente o `.env` do projeto
- resolve `NETPULSE_DB_PATH` ou `NETPULSE_DATA_DIR`
- garante que as tabelas novas existam
- recria agregados horários e diários
- recompõe incidentes por tipo
- recompõe os agregados de latência de TCP e DNS a partir de `samples`

Se preferir rodar dentro do container:

```bash
docker compose exec netpulse python /app/scripts/repair_db.py
```

## Configuração

Arquivo principal:

- [`netpulse/.env`](/Volumes/homeX/git/homelab/netpulse/.env)

Parâmetros mais importantes:

| Variável | Descrição |
| --- | --- |
| `NETPULSE_PORT` | Porta local do dashboard |
| `NETPULSE_DATA_DIR` | Diretório persistente do banco SQLite |
| `NETPULSE_POLL_INTERVAL_SECONDS` | Intervalo entre coletas |
| `NETPULSE_LOG_RETENTION_DAYS` | Quantos dias manter nos logs brutos |
| `NETPULSE_LOG_MAX_SIZE_MB` | Tamanho máximo dos logs brutos |
| `NETPULSE_GRAPH_RETENTION_DAYS` | Quantos dias manter nos dados agregados do gráfico |
| `NETPULSE_DNS_HOSTNAME` | Hostname usado nas consultas DNS |
| `NETPULSE_DNS_RESOLVERS` | Resolvedores testados |
| `NETPULSE_TCP_TARGETS` | Alvos TCP para validar conectividade IP |

## Retenção Inteligente

O Netpulse agora trabalha com duas camadas:

- logs brutos: usados para incidentes recentes e detalhes finos
- agregados de gráfico: usados para guardar histórico por muito mais tempo

Os logs brutos são reciclados automaticamente quando qualquer um destes limites for atingido:

- dias máximos configurados
- tamanho máximo em MB

Os gráficos usam tabelas agregadas, então é viável guardar 6 meses ou mais sem crescer tanto.

## Consumo Esperado

Com intervalo de 30 segundos, o container faz apenas:

- 2 conexões TCP curtas
- 2 consultas DNS UDP

Isso é baixo o bastante para rodar continuamente sem pesar na rede doméstica.

## Interpretação Prática

- `offline`: a internet ou a rota externa provavelmente caiu.
- `dns_issue`: a rede está de pé, mas os resolvedores falharam no momento.
- `degraded`: existe falha parcial; vale investigar rota, filtro, latência ou assimetria entre alvos.

## Ajustes Recomendados

- Se quiser menor ruído, mantenha `30s` ou `60s`.
- Se quiser mais precisão para quedas curtas, use `15s`.
- Se quiser armazenar fora do repositório, ajuste `NETPULSE_DATA_DIR` para um path em `/mnt/...`.
- Se quiser seis meses de gráfico, use `NETPULSE_GRAPH_RETENTION_DAYS=180`.
