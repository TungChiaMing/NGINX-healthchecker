-- save.lua
wrk.method = "GET"
wrk.headers["Connection"] = "close"

local response_counter = 0
local responses = {}
local max_store = 100  -- 存前 100 個回應
local max_body_len = 1000  -- 每個 body 最多截斷 1000 字元

function response(status, headers, body)
    response_counter = response_counter + 1
    if response_counter <= max_store then
        local b = body or ""
        b = string.sub(tostring(b), 1, max_body_len)
        table.insert(responses, {status=status, body=b})
    end
end

function done(summary, latency, requests)
    io.write("=== Saved Responses (up to "..max_store..") ===\n")
    for i, r in ipairs(responses) do
        io.write("=== Response "..i.." ===\n")
        io.write("Status: "..r.status.."\n")
        io.write("Body:\n"..r.body.."\n\n")
    end
end